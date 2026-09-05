import logging
from datetime import date, timedelta
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, Prefetch, Q
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.accounts.permissions import privileged_mfa_required
from apps.accounts.services import mfa_verified
from apps.analytics.enums import EventName
from apps.analytics.services import AnalyticsError, record_event
from apps.blogs.markdown import MarkdownValidationError, render_markdown
from apps.github_sync.models import GithubIssueSnapshot, RepositoryConnection
from apps.github_sync.services import starter_tasks_for_project
from apps.ministries.enums import ContactVerificationStatus, OrgStatus, PublisherStatus
from apps.ministries.models import MinistryOrganization, MinistryPublisher
from apps.ministries.services import is_publisher_active
from apps.projects.enums import (
    ApplicationEventType,
    ApplicationStatus,
    ContributionMode,
    DifficultyLevel,
    EffortBand,
    ProjectStatus,
    ProjectType,
    TaskStatus,
)
from apps.projects.forms import (
    GovernmentDraftCreateForm,
    PersonalProjectForm,
    PersonalProjectWorkflowForm,
    ProjectAttachmentForm,
    ProjectAuthoringForm,
    ProjectCompletionForm,
    ProjectMaintainerForm,
    ProjectMilestoneForm,
    ProjectReviewAssignmentForm,
    ProjectReviewDecisionForm,
    ProjectScreeningQuestionForm,
    ProjectTaskForm,
    ProjectUpdateForm,
    ProjectWorkflowForm,
    SuitabilityChecklistForm,
    editable_project_fields,
)
from apps.projects.models import (
    Application,
    Project,
    ProjectBookmark,
    ProjectSuitability,
    ProjectTask,
)
from apps.projects.services import (
    APPLICATION_DECISION_TRANSITIONS,
    EDITABLE_STATES,
    ApplicationAuthorizationError,
    ApplicationDecisionError,
    ApplicationError,
    AttachmentError,
    MaterialEditError,
    ProjectAuthorizationError,
    ProjectLifecycleError,
    PublishReadinessError,
    accept_community_terms,
    add_attachment,
    add_screening_question,
    apply_edit,
    apply_to_project,
    approve,
    archive,
    assign_maintainer,
    assign_reviewer,
    can_view_timeline,
    cancel,
    check_publish_readiness,
    complete,
    complete_suitability,
    confirm_suitability,
    create_government_draft,
    create_milestone,
    create_personal_draft,
    create_task,
    current_community_terms_version,
    decide_application,
    extend_deadline,
    has_accepted_community_terms,
    latest_public_update,
    maintainer_response_stale,
    open_personal_listing,
    pause,
    post_update,
    projects_for_publisher,
    provide_info,
    publish,
    publish_by_publisher,
    reject_submission,
    remove_screening_question,
    request_changes,
    request_github_ownership_verification,
    response_overdue,
    restore,
    resubmit,
    resume,
    revoke_approval,
    save_completion_summary,
    set_screening_question_active,
    submit_for_review,
    unpublish_personal_listing,
    withdraw_application,
)
from apps.taxonomy.enums import ContentLanguage, TermVocabulary
from apps.taxonomy.fields import normalize_nfc
from apps.taxonomy.models import Skill, TaxonomyTerm

logger = logging.getLogger(__name__)

PUBLIC_PROJECT_STATUSES = (
    ProjectStatus.OPEN_FOR_CONTRIBUTION,
    ProjectStatus.PAUSED,
    ProjectStatus.COMPLETED,
    ProjectStatus.CANCELLED,
    ProjectStatus.ARCHIVED,
)

AUTHORING_TABS = ("overview", "readiness", "attachments", "updates", "questions")

AUTHORING_MANAGE_TABS = {
    "maintainer": "overview",
    "task": "overview",
    "milestone": "overview",
    "suitability": "readiness",
    "confirm_suitability": "readiness",
    "update": "updates",
    "screening_question": "questions",
    "screening_toggle": "questions",
    "screening_remove": "questions",
}


def public_projects():
    return (
        Project.objects.filter(status__in=PUBLIC_PROJECT_STATUSES)
        .select_related("ministry")
        .prefetch_related("contribution_types", "skills", "technologies", "milestones")
    )


def home(request: HttpRequest) -> HttpResponse:
    """DSC-001/GOV-008: focused public entry point for government GitHub work."""
    featured_projects = (
        public_projects()
        .filter(
            project_type=ProjectType.GOVERNMENT,
            status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
        )
        .order_by("-published_at", "-id")[:3]
    )
    return render(
        request,
        "projects/home.html",
        {
            "featured_projects": featured_projects,
        },
    )


def about(request: HttpRequest) -> HttpResponse:
    """DSC-001/NFR-I18N-01: explain the public contribution path and safeguards."""
    return render(request, "projects/about.html")


def code_of_conduct(request: HttpRequest) -> HttpResponse:
    """A1.1/B6: publish the behavioral contract linked by the prototype shell."""
    return render(
        request,
        "projects/public_trust_page.html",
        {
            "kicker": _("Trust and safety"),
            "title": _("Code of conduct"),
            "lede": _(
                "DevNepal is a public-service collaboration space. Participation must remain "
                "respectful, specific, and safe for contributors and government staff."
            ),
            "sections": (
                (
                    _("Expected conduct"),
                    _(
                        "Discuss the work, not the person. Respect privacy, accessibility needs, "
                        "language choice, and the published contribution process."
                    ),
                ),
                (
                    _("Unacceptable conduct"),
                    _(
                        "Harassment, discrimination, threats, doxxing, credential sharing, and "
                        "publishing personal or restricted government data are prohibited."
                    ),
                ),
                (
                    _("Reporting"),
                    _(
                        "Reports are handled privately, recorded as cases, and reviewed with a "
                        "reasoned, appealable decision."
                    ),
                ),
            ),
        },
    )


def privacy_policy(request: HttpRequest) -> HttpResponse:
    """A1.1/B5: explain the public platform privacy boundary without requiring sign-in."""
    return render(
        request,
        "projects/public_trust_page.html",
        {
            "kicker": _("Privacy"),
            "title": _("Your data stays under your control"),
            "lede": _(
                "Public profiles, leaderboard participation, and connected GitHub access are "
                "separate choices. DevNepal does not make private profile fields public."
            ),
            "sections": (
                (
                    _("Public by choice"),
                    _("Members choose whether their profile and recognition appear publicly."),
                ),
                (
                    _("GitHub boundary"),
                    _(
                        "Repository access is limited to the permissions shown during connection "
                        "and can be disconnected."
                    ),
                ),
                (
                    _("Access and deletion"),
                    _(
                        "Signed-in members can export their data and request deletion from privacy "
                        "settings."
                    ),
                ),
            ),
        },
    )


def security_policy(request: HttpRequest) -> HttpResponse:
    """A1.1/B6: publish a safe disclosure path instead of exposing operational secrets."""
    return render(
        request,
        "projects/public_trust_page.html",
        {
            "kicker": _("Security"),
            "title": _("Report vulnerabilities responsibly"),
            "lede": _(
                "Do not post security findings, credentials, personal data, or production data "
                "in public issues, project applications, or contribution evidence."
            ),
            "sections": (
                (
                    _("Project findings"),
                    _(
                        "Use the security contact and disclosure policy published on the relevant "
                        "project sheet."
                    ),
                ),
                (
                    _("Platform findings"),
                    _(
                        "Use the confidential report form and include only the minimum evidence "
                        "needed to reproduce the issue."
                    ),
                ),
                (
                    _("What happens next"),
                    _(
                        "A case is acknowledged, triaged privately, and retained in the audited "
                        "moderation workflow."
                    ),
                ),
            ),
        },
    )


def ministry_onboarding(request: HttpRequest) -> HttpResponse:
    """C1.1/C1.3/GOV-001: explain the verified ministry publishing path publicly."""
    return render(request, "projects/ministry_onboarding.html")


def project_list(request: HttpRequest, project_type: str | None = None) -> HttpResponse:
    """DSC-001/DSC-002: public project browse and explicit catalog filtering."""
    catalog = public_projects()
    projects = catalog
    selected_type = project_type or normalize_nfc(request.GET.get("type", ""))
    if selected_type in ProjectType.values:
        catalog = catalog.filter(project_type=selected_type)
        projects = catalog
    else:
        selected_type = ""

    status_counts = {
        ProjectStatus.OPEN_FOR_CONTRIBUTION: 0,
        ProjectStatus.PAUSED: 0,
        ProjectStatus.COMPLETED: 0,
    }
    for row in (
        catalog.filter(status__in=status_counts).values("status").annotate(total=Count("pk"))
    ):
        status_counts[row["status"]] = row["total"]

    query = normalize_nfc(request.GET.get("q", ""))
    if query:
        projects = projects.filter(
            Q(title_en__icontains=query)
            | Q(title_ne__icontains=query)
            | Q(summary_en__icontains=query)
            | Q(summary_ne__icontains=query)
        )

    ministry = normalize_nfc(request.GET.get("ministry", ""))
    if ministry:
        projects = projects.filter(ministry__slug=ministry)

    contribution_type = normalize_nfc(request.GET.get("contribution_type", ""))
    if contribution_type:
        projects = projects.filter(contribution_types__slug=contribution_type)

    skill = normalize_nfc(request.GET.get("skill", ""))
    if skill:
        projects = projects.filter(skills__slug=skill)

    technology = normalize_nfc(request.GET.get("technology", ""))
    if technology:
        projects = projects.filter(technologies__slug=technology)

    difficulty = normalize_nfc(request.GET.get("difficulty", ""))
    if difficulty in DifficultyLevel.values:
        projects = projects.filter(difficulty=difficulty)
    else:
        difficulty = ""

    effort = normalize_nfc(request.GET.get("effort", ""))
    if effort in EffortBand.values:
        projects = projects.filter(estimated_effort=effort)
    else:
        effort = ""

    language = normalize_nfc(request.GET.get("language", ""))
    if language == "ne":
        projects = projects.exclude(title_ne="")
    elif language == "en":
        projects = projects.exclude(title_en="")
    else:
        language = ""

    status = normalize_nfc(request.GET.get("status", ""))
    if status in PUBLIC_PROJECT_STATUSES:
        projects = projects.filter(status=status)
    else:
        status = ""

    deadline_from = normalize_nfc(request.GET.get("deadline_from", ""))
    try:
        if deadline_from:
            projects = projects.filter(deadline__gte=date.fromisoformat(deadline_from))
    except ValueError:
        deadline_from = ""

    deadline_to = normalize_nfc(request.GET.get("deadline_to", ""))
    try:
        if deadline_to:
            projects = projects.filter(deadline__lte=date.fromisoformat(deadline_to))
    except ValueError:
        deadline_to = ""

    projects = projects.annotate(
        open_task_count=Count(
            "tasks",
            filter=Q(tasks__status=TaskStatus.OPEN),
            distinct=True,
        )
    )

    sort = normalize_nfc(request.GET.get("sort", "updated"))
    ordering = {
        "updated": ("-updated_at", "-pk"),
        "deadline": (F("deadline").asc(nulls_last=True), "title_en", "pk"),
        "title": ("title_en", "pk"),
    }
    if sort not in ordering:
        sort = "updated"
    projects = projects.order_by(*ordering[sort])

    layout = normalize_nfc(request.GET.get("layout", "grid"))
    if layout not in {"grid", "list"}:
        layout = "grid"

    filters = {
        "q": query,
        "type": selected_type,
        "ministry": ministry,
        "technology": technology,
        "contribution_type": contribution_type,
        "skill": skill,
        "status": status,
        "difficulty": difficulty,
        "effort": effort,
        "deadline_from": deadline_from,
        "deadline_to": deadline_to,
        "language": language,
        "sort": sort,
        "layout": layout,
    }
    query_string = urlencode({key: value for key, value in filters.items() if value})

    ministries = list(
        MinistryOrganization.objects.filter(projects__status__in=PUBLIC_PROJECT_STATUSES)
        .order_by("name_en")
        .distinct()
    )
    technologies = list(
        TaxonomyTerm.objects.filter(
            vocabulary=TermVocabulary.TECHNOLOGY,
            is_active=True,
            technology_projects__status__in=PUBLIC_PROJECT_STATUSES,
        ).distinct()
    )
    contribution_types = list(
        TaxonomyTerm.objects.filter(
            vocabulary=TermVocabulary.CONTRIBUTION_TYPE,
            is_active=True,
            projects__status__in=PUBLIC_PROJECT_STATUSES,
        ).distinct()
    )
    skills = list(
        Skill.objects.filter(
            is_active=True,
            projects__status__in=PUBLIC_PROJECT_STATUSES,
        ).distinct()
    )
    filter_value_labels = {
        "ministry": {item.slug: item.localized_name for item in ministries},
        "technology": {item.slug: item.label for item in technologies},
        "contribution_type": {item.slug: item.label for item in contribution_types},
        "skill": {item.slug: item.name for item in skills},
        "status": dict(ProjectStatus.choices),
        "difficulty": dict(DifficultyLevel.choices),
        "effort": dict(EffortBand.choices),
        "language": dict(ContentLanguage.choices),
    }

    active_filters = [
        {
            "label": label,
            "value": filter_value_labels.get(key, {}).get(filters[key], filters[key]),
        }
        for key, label in (
            ("q", _("Search")),
            ("ministry", _("Ministry")),
            ("technology", _("Technology")),
            ("contribution_type", _("Contribution type")),
            ("skill", _("Skill")),
            ("status", _("Status")),
            ("difficulty", _("Difficulty")),
            ("effort", _("Effort")),
            ("deadline_from", _("Deadline from")),
            ("deadline_to", _("Deadline to")),
            ("language", _("Language")),
        )
        if filters[key]
    ]

    page = Paginator(projects.distinct(), 24).get_page(request.GET.get("page"))
    return render(
        request,
        "projects/project_list.html",
        {
            "projects": page,
            "project_type": selected_type,
            "query": query,
            "filters": filters,
            "query_string": query_string,
            "active_filters": active_filters,
            "sort": sort,
            "layout": layout,
            "sort_choices": (
                ("updated", _("Recently updated")),
                ("deadline", _("Deadline soonest")),
                ("title", _("Title A to Z")),
            ),
            "status_counts": status_counts,
            "status_summary": (
                (_("open"), status_counts[ProjectStatus.OPEN_FOR_CONTRIBUTION]),
                (_("paused"), status_counts[ProjectStatus.PAUSED]),
                (_("completed"), status_counts[ProjectStatus.COMPLETED]),
            ),
            "public_statuses": PUBLIC_PROJECT_STATUSES,
            "public_status_choices": [
                (status, ProjectStatus(status).label) for status in PUBLIC_PROJECT_STATUSES
            ],
            "project_types": ProjectType,
            "difficulties": DifficultyLevel,
            "effort_bands": EffortBand,
            "languages": ContentLanguage,
            "ministries": ministries,
            "technologies": technologies,
            "contribution_types": contribution_types,
            "skills": skills,
        },
    )


def project_detail(request: HttpRequest, slug: str) -> HttpResponse:
    """ANL-001/DSC-003/GOV-011: render a public project with government view telemetry."""
    project = get_object_or_404(
        public_project_details(),
        slug=normalize_nfc(slug),
    )
    if project.project_type == ProjectType.GOVERNMENT:
        try:
            record_event(EventName.PROJECT_VIEWED, project=project)
        except AnalyticsError:
            logger.exception("Project-view analytics recording failed; project_id=%s", project.pk)
    return render(request, "projects/project_detail.html", public_project_detail_context(project))


def project_updates(request: HttpRequest, slug: str) -> HttpResponse:
    """DSC-009: the public progress-update timeline for a published project."""
    project = get_object_or_404(public_project_details(), slug=normalize_nfc(slug))
    return render(
        request,
        "projects/project_updates.html",
        {"project": project, "updates": project.updates.all},
    )


def github_issue_detail(request: HttpRequest, slug: str, number: int) -> HttpResponse:
    """DSC-005/GIT-010: show a bounded public GitHub issue snapshot inside DevNepal."""
    issue = get_object_or_404(
        GithubIssueSnapshot.objects.select_related(
            "repository__project", "repository__project__ministry"
        ),
        repository__project__slug=normalize_nfc(slug),
        repository__project__status__in=PUBLIC_PROJECT_STATUSES,
        repository__is_public=True,
        repository__deactivated_at__isnull=True,
        number=number,
    )
    try:
        issue_body_html = render_markdown(issue.body)
    except MarkdownValidationError:
        logger.warning(
            "public GitHub issue markdown could not be rendered (repository=%s issue=%s)",
            issue.repository.full_name,
            issue.number,
        )
        issue_body_html = None
    return render(
        request,
        "projects/github_issue_detail.html",
        {
            "project": issue.repository.project,
            "repository": issue.repository,
            "issue": issue,
            "issue_body_html": issue_body_html,
        },
    )


def public_project_details():
    return (
        public_projects()
        .select_related("license")
        .prefetch_related(
            "links",
            "updates",
            "screening_questions",
            "maintainer_assignments__user",
            Prefetch(
                "tasks",
                queryset=ProjectTask.objects.filter(status=TaskStatus.OPEN).prefetch_related(
                    "skills"
                ),
                to_attr="open_tasks",
            ),
            Prefetch(
                "repository_connections",
                queryset=RepositoryConnection.objects.filter(
                    is_public=True, deactivated_at__isnull=True
                ).prefetch_related(
                    "issue_snapshots", "pull_request_snapshots", "contributor_snapshots"
                ),
                to_attr="public_repositories",
            ),
        )
    )


def public_project_detail_context(project: Project, **extra) -> dict:
    """DSC-009: public activity indicators without exposing private operational data."""
    moment = timezone.now()
    live = project.status in {ProjectStatus.OPEN_FOR_CONTRIBUTION, ProjectStatus.PAUSED}
    latest_update = latest_public_update(project)
    last_activity_at = (
        project.last_maintainer_activity_at
        or (latest_update.created_at if latest_update else None)
        or project.published_at
    )
    github_starter_tasks, github_repositories = starter_tasks_for_project(project)
    public_repositories = getattr(project, "public_repositories", [])
    return {
        "project": project,
        "open_tasks": project.open_tasks,
        "supports_direct_contributions": project.contribution_mode
        in {ContributionMode.OPEN_DIRECT, ContributionMode.HYBRID},
        "requires_application": project.contribution_mode
        in {ContributionMode.APPLICATION, ContributionMode.HYBRID},
        "last_activity_at": last_activity_at,
        "last_activity_days_ago": ((moment - last_activity_at).days if last_activity_at else None),
        "response_overdue": response_overdue(project, now=moment) if live else False,
        "maintainer_stale": maintainer_response_stale(project, now=moment) if live else False,
        "github_starter_tasks": github_starter_tasks,
        "github_repositories": github_repositories,
        "github_issues": [
            issue
            for repository in public_repositories
            for issue in repository.issue_snapshots.all()
        ],
        "github_pull_requests": [
            pull_request
            for repository in public_repositories
            for pull_request in repository.pull_request_snapshots.all()
        ],
        "github_contributors": [
            contributor
            for repository in public_repositories
            for contributor in repository.contributor_snapshots.all()
        ],
        "public_github_repositories": public_repositories,
        **extra,
    }


def _can_author_projects(user) -> bool:
    return bool(
        user.is_active
        and (
            user.is_superuser
            or MinistryPublisher.objects.filter(
                user=user,
                status=PublisherStatus.ACTIVE,
                contact_verification_status=ContactVerificationStatus.VERIFIED,
                ministry__status=OrgStatus.ACTIVE,
            ).exists()
        )
    )


def _manageable_project_or_404(user, slug: str) -> Project:
    project = get_object_or_404(
        Project.objects.select_related("ministry", "license").prefetch_related(
            "contribution_types",
            "skills",
            "technologies",
            "reviews__reviewer",
            "maintainer_assignments__user",
            "screening_questions",
            "tasks__skills",
            "milestones",
            "attachments",
            "updates",
            "repository_connections__issue_snapshots",
            "repository_connections__pull_request_snapshots",
            "repository_connections__contributor_snapshots",
        ),
        slug=normalize_nfc(slug),
        project_type=ProjectType.GOVERNMENT,
    )
    if not user.is_superuser and not is_publisher_active(user, project.ministry):
        raise Http404
    return project


def _allowed_workflow_actions(user, project: Project) -> set[str]:
    status_actions = {
        ProjectStatus.DRAFT: {"submit", "publish"},
        ProjectStatus.IN_REVIEW: {"request_changes", "reject", "approve"},
        ProjectStatus.CHANGES_REQUESTED: {"resubmit"},
        ProjectStatus.APPROVED: {"publish", "revoke_approval"},
        ProjectStatus.OPEN_FOR_CONTRIBUTION: {
            "pause",
            "complete",
            "cancel",
            "extend_deadline",
            "archive",
        },
        ProjectStatus.PAUSED: {"resume", "complete", "cancel", "extend_deadline", "archive"},
        ProjectStatus.COMPLETED: {"archive"},
        ProjectStatus.CANCELLED: {"archive"},
        ProjectStatus.ARCHIVED: {"restore"},
    }
    actions = status_actions[project.status]
    if user.is_superuser:
        return actions
    if not is_publisher_active(user, project.ministry):
        return set()
    return actions - {
        "request_changes",
        "reject",
        "approve",
        "revoke_approval",
        "restore",
    }


def _authoring_context(
    project: Project,
    *,
    user,
    tab: str = "overview",
    form=None,
    workflow_form=None,
    update_form=None,
    attachment_form=None,
    screening_question_form=None,
    error="",
) -> dict:
    suitability = (
        ProjectSuitability.objects.filter(project=project)
        .select_related("completed_by", "confirmed_by")
        .first()
    )
    return {
        "project": project,
        "active_tab": tab,
        "form": form,
        "workflow_form": workflow_form
        or ProjectWorkflowForm(allowed_actions=_allowed_workflow_actions(user, project)),
        "editable": project.status in EDITABLE_STATES,
        "error": error,
        "maintainer_form": ProjectMaintainerForm(),
        "task_form": ProjectTaskForm(),
        "milestone_form": ProjectMilestoneForm(),
        "update_form": update_form or ProjectUpdateForm(),
        "attachment_form": attachment_form or ProjectAttachmentForm(),
        "screening_question_form": screening_question_form or ProjectScreeningQuestionForm(),
        "suitability_form": SuitabilityChecklistForm(
            checklist=suitability.checklist if suitability else None,
            initial={"notes": suitability.notes if suitability else ""},
        ),
        "suitability": suitability,
        "publish_readiness_violations": check_publish_readiness(project),
        "can_confirm_suitability": user.is_superuser and suitability is not None,
        "system_label": _("System"),
    }


def _save_authoring_many_to_many(form: ProjectAuthoringForm, project: Project) -> None:
    for field_name in ("contribution_types", "skills", "technologies"):
        getattr(project, field_name).set(form.cleaned_data[field_name])


def _manageable_community_project_or_404(user, slug: str) -> Project:
    return get_object_or_404(
        Project.objects.select_related("owner").prefetch_related("technologies", "skills"),
        slug=normalize_nfc(slug),
        project_type=ProjectType.PERSONAL,
        owner=user,
    )


def _community_workflow_actions(project: Project) -> set[str]:
    if project.status == ProjectStatus.DRAFT:
        return {"publish"}
    if project.status == ProjectStatus.OPEN_FOR_CONTRIBUTION:
        return {"unpublish", "archive"}
    if project.status in {ProjectStatus.PAUSED, ProjectStatus.COMPLETED, ProjectStatus.CANCELLED}:
        return {"archive"}
    return set()


def _save_community_many_to_many(form: PersonalProjectForm, project: Project) -> None:
    for field_name in ("technologies", "skills"):
        getattr(project, field_name).set(form.cleaned_data[field_name])


@login_required(login_url=reverse_lazy("accounts:login"))
def community_dashboard(request: HttpRequest) -> HttpResponse:
    """PPR-001/PPR-003/PPR-006: the member's community projects and terms status."""
    projects = (
        Project.objects.filter(project_type=ProjectType.PERSONAL, owner=request.user)
        .select_related("owner")
        .prefetch_related("technologies", "skills")
    )
    return render(
        request,
        "projects/community_dashboard.html",
        {
            "projects": projects,
            "terms_version": current_community_terms_version(),
            "terms_accepted": has_accepted_community_terms(request.user),
        },
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@require_POST
def community_accept_terms(request: HttpRequest) -> HttpResponse:
    """PPR-006: record the member's acceptance of the current community terms."""
    try:
        accept_community_terms(request.user)
    except ProjectAuthorizationError as error:
        raise PermissionDenied from error
    return redirect("projects:community_dashboard")


@login_required(login_url=reverse_lazy("accounts:login"))
@require_POST
def community_verify_github(request: HttpRequest, slug: str) -> HttpResponse:
    """PPR-004: the owner requests GitHub ownership verification for their listing."""
    project = _manageable_community_project_or_404(request.user, slug)
    try:
        request_github_ownership_verification(request.user, project)
    except ProjectAuthorizationError as error:
        raise PermissionDenied from error
    except ProjectLifecycleError as error:
        return render(
            request,
            "projects/community_detail.html",
            {
                "project": project,
                "workflow_form": PersonalProjectWorkflowForm(
                    allowed_actions=_community_workflow_actions(project)
                ),
                "editable": project.status in EDITABLE_STATES,
                "error": str(error),
            },
            status=400,
        )
    return redirect("projects:community_detail", slug=project.slug)


@login_required(login_url=reverse_lazy("accounts:login"))
def community_create(request: HttpRequest) -> HttpResponse:
    """PPR-001/PPR-002: an authenticated member creates a ministry-free community draft."""
    if request.method == "POST":
        form = PersonalProjectForm(request.POST)
        if form.is_valid():
            fields = {
                name: value
                for name, value in form.cleaned_data.items()
                if name not in {"technologies", "skills"}
            }
            try:
                project = create_personal_draft(request.user, **fields)
            except ProjectAuthorizationError as error:
                raise PermissionDenied from error
            _save_community_many_to_many(form, project)
            return redirect("projects:community_edit", slug=project.slug)
    else:
        form = PersonalProjectForm()
    return render(request, "projects/community_form.html", {"form": form, "is_create": True})


@login_required(login_url=reverse_lazy("accounts:login"))
def community_edit(request: HttpRequest, slug: str) -> HttpResponse:
    """PPR-001/AUTH-006: owners edit only their personal drafts or active listings."""
    project = _manageable_community_project_or_404(request.user, slug)
    if request.method == "POST" and project.status in EDITABLE_STATES:
        form = PersonalProjectForm(request.POST, instance=project)
        if form.is_valid():
            try:
                apply_edit(request.user, project, **editable_project_fields(form))
            except (MaterialEditError, ProjectAuthorizationError) as error:
                return render(
                    request,
                    "projects/community_form.html",
                    {"form": form, "project": project, "error": str(error)},
                    status=400,
                )
            _save_community_many_to_many(form, project)
            return redirect("projects:community_edit", slug=project.slug)
    else:
        form = PersonalProjectForm(instance=project)
    return render(
        request,
        "projects/community_form.html",
        {
            "form": form,
            "project": project,
            "is_create": False,
            "editable": project.status in EDITABLE_STATES,
        },
    )


@login_required(login_url=reverse_lazy("accounts:login"))
def community_detail(request: HttpRequest, slug: str) -> HttpResponse:
    """PPR-001/PPR-003: show an owner-scoped community lifecycle record."""
    project = _manageable_community_project_or_404(request.user, slug)
    return render(
        request,
        "projects/community_detail.html",
        {
            "project": project,
            "workflow_form": PersonalProjectWorkflowForm(
                allowed_actions=_community_workflow_actions(project)
            ),
            "editable": project.status in EDITABLE_STATES,
        },
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@require_POST
def community_workflow(request: HttpRequest, slug: str) -> HttpResponse:
    """PPR-001: owners publish, unpublish, or archive their own community listing."""
    project = _manageable_community_project_or_404(request.user, slug)
    form = PersonalProjectWorkflowForm(
        request.POST, allowed_actions=_community_workflow_actions(project)
    )
    if not form.is_valid():
        return render(
            request,
            "projects/community_detail.html",
            {
                "project": project,
                "workflow_form": form,
                "editable": project.status in EDITABLE_STATES,
            },
            status=400,
        )
    actions = {
        "publish": lambda: open_personal_listing(request.user, project),
        "unpublish": lambda: unpublish_personal_listing(request.user, project),
        "archive": lambda: archive(request.user, project, reason=form.cleaned_data["reason"]),
    }
    try:
        actions[form.cleaned_data["action"]]()
    except ProjectAuthorizationError as error:
        raise PermissionDenied from error
    except ProjectLifecycleError as error:
        project.refresh_from_db()
        return render(
            request,
            "projects/community_detail.html",
            {
                "project": project,
                "workflow_form": form,
                "editable": project.status in EDITABLE_STATES,
                "error": str(error),
            },
            status=400,
        )
    return redirect("projects:community_detail", slug=project.slug)


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
def authoring_dashboard(request: HttpRequest) -> HttpResponse:
    """GOV-001/GOV-004: list only government projects the privileged user may author or review."""
    if not _can_author_projects(request.user):
        raise PermissionDenied
    projects = (
        Project.objects.filter(project_type=ProjectType.GOVERNMENT)
        if request.user.is_superuser
        else projects_for_publisher(request.user)
    )
    return render(
        request,
        "projects/authoring_dashboard.html",
        {
            "projects": projects.select_related("ministry"),
            "can_create": _can_author_projects(request.user),
        },
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
def review_queue(request: HttpRequest) -> HttpResponse:
    """ADM-002/GOV-005/D2: PMO queue, assignment, comparison, and decisions."""
    if not request.user.is_active or not request.user.is_superuser:
        raise PermissionDenied
    projects_query = Project.objects.filter(
        project_type=ProjectType.GOVERNMENT,
        status__in={
            ProjectStatus.IN_REVIEW,
            ProjectStatus.CHANGES_REQUESTED,
            ProjectStatus.APPROVED,
        },
    )
    allowed_state_filters = {
        ProjectStatus.IN_REVIEW,
        ProjectStatus.CHANGES_REQUESTED,
        ProjectStatus.APPROVED,
    }
    state_filter = request.GET.get("state", "")
    if state_filter in allowed_state_filters:
        projects_query = projects_query.filter(status=state_filter)
    else:
        state_filter = ""
    assigned_filter = "me" if request.GET.get("assigned") == "me" else ""
    if assigned_filter:
        projects_query = projects_query.filter(review_assignment__reviewer=request.user)
    projects = list(
        projects_query.select_related("ministry", "review_assignment__reviewer")
        .prefetch_related("versions", "reviews", "attachments", "suitability")
        .order_by("status_changed_at", "pk")
    )
    selected = next(
        (item for item in projects if item.slug == request.GET.get("project")),
        projects[0] if projects else None,
    )
    assignment_form = ProjectReviewAssignmentForm()
    decision_form = ProjectReviewDecisionForm(allowed_actions=_review_actions(selected))
    error = ""
    if request.method == "POST":
        selected = next(
            (item for item in projects if item.slug == request.POST.get("project")), None
        )
        if selected is None:
            raise Http404
        intent = request.POST.get("intent")
        try:
            if intent == "assign":
                assignment_form = ProjectReviewAssignmentForm(request.POST)
                if assignment_form.is_valid():
                    assign_reviewer(
                        request.user,
                        selected,
                        reviewer=assignment_form.cleaned_data["reviewer"],
                        due_at=assignment_form.cleaned_data["due_at"],
                        reviewer_note=assignment_form.cleaned_data["reviewer_note"],
                        checklist=assignment_form.checklist(),
                    )
                else:
                    error = _("Correct the reviewer assignment errors below.")
            elif intent == "decision":
                decision_form = ProjectReviewDecisionForm(
                    request.POST, allowed_actions=_review_actions(selected)
                )
                if decision_form.is_valid():
                    action = decision_form.cleaned_data["action"]
                    comment = decision_form.cleaned_data["comment"]
                    decisions = {
                        "request_changes": lambda: request_changes(
                            request.user, selected, reason=comment
                        ),
                        "reject": lambda: reject_submission(request.user, selected, reason=comment),
                        "approve": lambda: approve(
                            request.user,
                            selected,
                            publish_at=decision_form.cleaned_data["publish_at"],
                            comment=comment,
                        ),
                        "revoke_approval": lambda: revoke_approval(
                            request.user, selected, reason=comment
                        ),
                        "publish": lambda: publish(request.user, selected, comment=comment),
                    }
                    decisions[action]()
                else:
                    error = _("Correct the review decision errors below.")
            else:
                raise ProjectLifecycleError(_("Unknown review action."))
        except ProjectAuthorizationError as exc:
            raise PermissionDenied from exc
        except (ProjectLifecycleError, PublishReadinessError) as exc:
            error = str(exc)
        if not error:
            query = {"project": selected.slug}
            if state_filter:
                query["state"] = state_filter
            if assigned_filter:
                query["assigned"] = assigned_filter
            return redirect(f"{reverse('projects:review_queue')}?{urlencode(query)}")
    now = timezone.now()
    queue = []
    for item in projects:
        version = item.versions.order_by("-version_number").first()
        assignment = getattr(item, "review_assignment", None)
        submitted_at = (
            version.submitted_at if version else item.status_changed_at or item.created_at
        )
        current_assignment = (
            assignment
            if assignment and assignment.version_id == getattr(version, "pk", None)
            else None
        )
        due_at = (
            current_assignment.due_at if current_assignment else submitted_at + timedelta(days=5)
        )
        checklist = current_assignment.checklist if current_assignment else {}
        select_query = {"project": item.slug}
        if state_filter:
            select_query["state"] = state_filter
        if assigned_filter:
            select_query["assigned"] = assigned_filter
        queue.append(
            {
                "project": item,
                "version": version,
                "assignment": current_assignment,
                "checklist_done": sum(bool(value) for value in checklist.values()),
                "checklist_total": len(checklist),
                "sla_age": max(0, (now - submitted_at).days),
                "due_at": due_at,
                "overdue": due_at < now,
                "select_url": f"?{urlencode(select_query)}",
            }
        )
    return render(
        request,
        "projects/review_queue.html",
        {
            "queue": queue,
            "selected": selected,
            "assignment_form": assignment_form,
            "decision_form": decision_form,
            "version_diff": _project_version_diff(selected),
            "review_actions": _review_actions(selected),
            "error": error,
            "state_filter": state_filter,
            "assigned_filter": assigned_filter,
        },
        status=400 if error else 200,
    )


def _project_version_diff(project):
    if project is None:
        return []
    versions = list(project.versions.order_by("-version_number")[:2])
    if len(versions) < 2:
        return []
    current, previous = versions
    return [
        {
            "field": key,
            "before": previous.snapshot.get(key),
            "after": current.snapshot.get(key),
            "from_version": previous.version_number,
            "to_version": current.version_number,
        }
        for key in sorted(set(current.snapshot) | set(previous.snapshot))
        if previous.snapshot.get(key) != current.snapshot.get(key)
    ]


def _review_actions(project):
    if project is None:
        return set()
    return {
        ProjectStatus.IN_REVIEW: {"request_changes", "reject", "approve"},
        ProjectStatus.APPROVED: {"revoke_approval", "publish"},
        ProjectStatus.CHANGES_REQUESTED: set(),
    }.get(project.status, set())


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
def authoring_create(request: HttpRequest) -> HttpResponse:
    """GOV-001/GOV-002: create a ministry-scoped government project draft."""
    if not _can_author_projects(request.user):
        raise PermissionDenied
    if request.method == "POST":
        form = GovernmentDraftCreateForm(request.POST, actor=request.user)
        if form.is_valid():
            fields = {
                name: value
                for name, value in form.cleaned_data.items()
                if name != "ministry"
                and name not in {"contribution_types", "skills", "technologies"}
            }
            try:
                project = create_government_draft(
                    request.user, form.cleaned_data["ministry"], **fields
                )
            except ProjectAuthorizationError as error:
                raise PermissionDenied from error
            _save_authoring_many_to_many(form, project)
            return redirect("projects:authoring_edit", slug=project.slug)
    else:
        form = GovernmentDraftCreateForm(actor=request.user)
    return render(request, "projects/authoring_form.html", {"form": form, "is_create": True})


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
def authoring_edit(request: HttpRequest, slug: str) -> HttpResponse:
    """GOV-001/GOV-006: edit only an authorized ministry project through the edit service."""
    project = _manageable_project_or_404(request.user, slug)
    if request.method == "POST" and project.status in EDITABLE_STATES:
        form = ProjectAuthoringForm(request.POST, instance=project)
        if form.is_valid():
            try:
                apply_edit(request.user, project, **editable_project_fields(form))
            except (MaterialEditError, ProjectAuthorizationError) as error:
                return render(
                    request,
                    "projects/authoring_form.html",
                    {"form": form, "project": project, "error": str(error)},
                    status=400,
                )
            _save_authoring_many_to_many(form, project)
            return redirect("projects:authoring_edit", slug=project.slug)
    else:
        form = ProjectAuthoringForm(instance=project)
    return render(
        request,
        "projects/authoring_form.html",
        {
            "form": form,
            "project": project,
            "is_create": False,
            "editable": project.status in EDITABLE_STATES,
        },
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
def completion_summary(request: HttpRequest, slug: str) -> HttpResponse:
    """GOV-004/GOV-009/C5.3: prepare closure evidence and complete the project."""
    project = _manageable_project_or_404(request.user, slug)
    editable = project.status in {
        ProjectStatus.OPEN_FOR_CONTRIBUTION,
        ProjectStatus.PAUSED,
    }
    form = ProjectCompletionForm(request.POST or None, instance=project)
    if request.method == "POST":
        if not editable:
            form.add_error(None, _("Only an open or paused project can be completed."))
        elif form.is_valid():
            intent = request.POST.get("intent", "")
            if intent not in {"save", "complete"}:
                form.add_error(None, _("Choose whether to save the summary or mark it completed."))
            else:
                try:
                    with transaction.atomic():
                        save_completion_summary(request.user, project, **form.cleaned_data)
                        if intent == "complete":
                            complete(request.user, project)
                except ProjectAuthorizationError as error:
                    raise PermissionDenied from error
                except ProjectLifecycleError as error:
                    form.add_error(None, str(error))
                else:
                    if intent == "complete":
                        return redirect("projects:authoring_detail", slug=project.slug)
                    return redirect("projects:completion_summary", slug=project.slug)
    return render(
        request,
        "projects/completion_form.html",
        {"project": project, "form": form, "editable": editable},
        status=400 if form.errors else 200,
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_POST
def authoring_workflow(request: HttpRequest, slug: str) -> HttpResponse:
    """GOV-004/GOV-005: execute authorized lifecycle commands through the state-machine services."""
    project = _manageable_project_or_404(request.user, slug)
    form = ProjectWorkflowForm(
        request.POST, allowed_actions=_allowed_workflow_actions(request.user, project)
    )
    if not form.is_valid():
        return render(
            request,
            "projects/authoring_detail.html",
            _authoring_context(project, user=request.user, workflow_form=form),
            status=400,
        )
    action = form.cleaned_data["action"]
    reason = form.cleaned_data["reason"]
    actions = {
        "submit": lambda: submit_for_review(request.user, project),
        "resubmit": lambda: resubmit(request.user, project),
        "request_changes": lambda: request_changes(request.user, project, reason=reason),
        "reject": lambda: reject_submission(request.user, project, reason=reason),
        "approve": lambda: approve(
            request.user,
            project,
            publish_at=form.cleaned_data["publish_at"],
            comment=reason,
        ),
        "revoke_approval": lambda: revoke_approval(request.user, project, reason=reason),
        "publish": lambda: (
            publish_by_publisher(request.user, project)
            if project.status == ProjectStatus.DRAFT
            else publish(request.user, project)
        ),
        "pause": lambda: pause(request.user, project),
        "resume": lambda: resume(request.user, project),
        "complete": lambda: complete(request.user, project),
        "cancel": lambda: cancel(request.user, project, reason=reason),
        "extend_deadline": lambda: extend_deadline(
            request.user, project, new_deadline=form.cleaned_data["new_deadline"]
        ),
        "archive": lambda: archive(request.user, project, reason=reason),
        "restore": lambda: restore(request.user, project),
    }
    try:
        actions[action]()
    except ProjectAuthorizationError as error:
        raise PermissionDenied from error
    except (ProjectLifecycleError, PublishReadinessError) as error:
        project.refresh_from_db()
        return render(
            request,
            "projects/authoring_detail.html",
            _authoring_context(project, user=request.user, workflow_form=form, error=str(error)),
            status=400,
        )
    return redirect("projects:authoring_detail", slug=project.slug)


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_POST
def authoring_manage(request: HttpRequest, slug: str) -> HttpResponse:
    """GOV-001/GOV-002/BR-002: manage authorized project readiness records through services."""
    project = _manageable_project_or_404(request.user, slug)
    action = request.POST.get("action", "")
    tab = AUTHORING_MANAGE_TABS.get(action, "overview")
    try:
        if action == "maintainer":
            form = ProjectMaintainerForm(request.POST)
            if form.is_valid():
                assign_maintainer(request.user, project, **form.cleaned_data)
            else:
                return _authoring_manage_error(request, project, "maintainer_form", form, tab)
        elif action == "task":
            form = ProjectTaskForm(request.POST)
            if form.is_valid():
                create_task(request.user, project, **form.cleaned_data)
            else:
                return _authoring_manage_error(request, project, "task_form", form, tab)
        elif action == "milestone":
            form = ProjectMilestoneForm(request.POST)
            if form.is_valid():
                create_milestone(request.user, project, **form.cleaned_data)
            else:
                return _authoring_manage_error(request, project, "milestone_form", form, tab)
        elif action == "update":
            form = ProjectUpdateForm(request.POST)
            if form.is_valid():
                post_update(request.user, project, **form.cleaned_data)
            else:
                return _authoring_manage_error(request, project, "update_form", form, tab)
        elif action == "suitability":
            form = SuitabilityChecklistForm(request.POST)
            if form.is_valid():
                checklist = {
                    name: {"checked": form.cleaned_data[name], "note": ""}
                    for name in form.fields
                    if name != "notes"
                }
                complete_suitability(
                    request.user,
                    project,
                    checklist=checklist,
                    notes=form.cleaned_data["notes"],
                )
            else:
                return _authoring_manage_error(request, project, "suitability_form", form, tab)
        elif action == "screening_question":
            form = ProjectScreeningQuestionForm(request.POST)
            if form.is_valid():
                add_screening_question(request.user, project, **form.cleaned_data)
            else:
                return _authoring_manage_error(
                    request, project, "screening_question_form", form, tab
                )
        elif action == "screening_toggle":
            set_screening_question_active(
                request.user,
                project,
                request.POST.get("question_id", ""),
                is_active=request.POST.get("is_active") == "1",
            )
        elif action == "screening_remove":
            remove_screening_question(request.user, project, request.POST.get("question_id", ""))
        elif action == "confirm_suitability":
            confirm_suitability(request.user, project)
        else:
            raise ProjectLifecycleError(_("Unknown authoring action."))
    except ProjectAuthorizationError as error:
        raise PermissionDenied from error
    except ProjectLifecycleError as error:
        return render(
            request,
            "projects/authoring_detail.html",
            _authoring_context(project, user=request.user, tab=tab, error=str(error)),
            status=400,
        )
    return redirect("projects:authoring_detail", slug=project.slug)


def _authoring_manage_error(
    request: HttpRequest, project: Project, form_name: str, form: object, tab: str = "overview"
) -> HttpResponse:
    context = _authoring_context(project, user=request.user, tab=tab)
    context[form_name] = form
    return render(request, "projects/authoring_detail.html", context, status=400)


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
def authoring_attachment(request: HttpRequest, slug: str) -> HttpResponse:
    """GOV-003/SEC-007: the attachments tab; POST uploads a validated, scan-tracked file."""
    project = _manageable_project_or_404(request.user, slug)
    if request.method == "GET":
        return render(
            request,
            "projects/authoring_detail.html",
            _authoring_context(project, user=request.user, tab="attachments"),
        )
    form = ProjectAttachmentForm(request.POST, request.FILES)
    if not form.is_valid():
        return _authoring_manage_error(request, project, "attachment_form", form, "attachments")
    try:
        add_attachment(request.user, project, **form.cleaned_data)
    except ProjectAuthorizationError as error:
        raise PermissionDenied from error
    except AttachmentError as error:
        return render(
            request,
            "projects/authoring_detail.html",
            _authoring_context(project, user=request.user, tab="attachments", error=str(error)),
            status=400,
        )
    return redirect("projects:authoring_attachment", slug=project.slug)


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
def authoring_detail(request: HttpRequest, slug: str, tab: str = "overview") -> HttpResponse:
    """GOV-004/GOV-005: show the authorized lifecycle state and review history for one tab."""
    if tab not in AUTHORING_TABS:
        raise Http404
    project = _manageable_project_or_404(request.user, slug)
    return render(
        request,
        "projects/authoring_detail.html",
        _authoring_context(
            project,
            user=request.user,
            tab=tab,
            form=ProjectAuthoringForm(instance=project),
        ),
    )


def _application_queryset():
    return Application.objects.select_related("applicant", "decided_by", "project__ministry")


def _applications_visible_to(user):
    applications = _application_queryset()
    if user.is_active and user.is_superuser:
        return applications
    return applications.filter(
        Q(applicant=user)
        | Q(project__project_type=ProjectType.PERSONAL, project__owner=user)
        | Q(
            project__project_type=ProjectType.GOVERNMENT,
            project__ministry__status=OrgStatus.ACTIVE,
            project__ministry__publishers__user=user,
            project__ministry__publishers__status=PublisherStatus.ACTIVE,
            project__ministry__publishers__contact_verification_status=ContactVerificationStatus.VERIFIED,
        )
    ).distinct()


def _visible_application_or_404(user, application_id: int) -> Application:
    application = get_object_or_404(_application_queryset(), pk=application_id)
    if not can_view_timeline(user, application):
        raise Http404
    return application


@login_required(login_url=reverse_lazy("accounts:login"))
def application_list(request: HttpRequest) -> HttpResponse:
    """DSC-008: list application records the authenticated user may view."""
    return render(
        request,
        "projects/application_list.html",
        {"applications": _applications_visible_to(request.user)},
    )


@login_required(login_url=reverse_lazy("accounts:login"))
def application_detail(request: HttpRequest, application_id: int) -> HttpResponse:
    """DSC-007/DSC-008: show an authorized application record and decision history."""
    application = _visible_application_or_404(request.user, application_id)
    decision_events = application.events.select_related("actor").filter(
        event__in=(ApplicationEventType.STATUS_CHANGED, ApplicationEventType.INFO_REQUESTED)
    )
    available_decisions = APPLICATION_DECISION_TRANSITIONS.get(application.status, set())
    return render(
        request,
        "projects/application_detail.html",
        {
            "application": application,
            "decision_history": _decision_history(decision_events),
            "decision_choices": [
                (decision, ApplicationStatus(decision).label)
                for decision in ApplicationStatus
                if decision in available_decisions
            ],
            "can_decide": _can_decide_application(request.user, application),
        },
    )


@login_required(login_url=reverse_lazy("accounts:login"))
def application_timeline(request: HttpRequest, application_id: int) -> HttpResponse:
    """DSC-008: show the append-only event history to an authorized user."""
    application = _visible_application_or_404(request.user, application_id)
    events = application.events.select_related("actor")
    return render(
        request,
        "projects/application_timeline.html",
        _timeline_context(request, application, events),
    )


def _timeline_context(request: HttpRequest, application: Application, events, **extra):
    context = {
        "application": application,
        "events": events,
        "withdrawal_available": request.user.pk == application.applicant_id
        and application.status
        in {
            ApplicationStatus.SUBMITTED,
            ApplicationStatus.INFO_REQUESTED,
            ApplicationStatus.WAITLISTED,
        },
        "can_provide_info": request.user.pk == application.applicant_id
        and application.status == ApplicationStatus.INFO_REQUESTED,
    }
    context.update(extra)
    return context


def _decision_history(events):
    return [
        {"event": event, "status": ApplicationStatus(event.to_status).label} for event in events
    ]


def _can_decide_application(user, application: Application) -> bool:
    if not mfa_verified(user):
        return False
    if user.is_active and user.is_superuser:
        return True
    return application.project.project_type == ProjectType.GOVERNMENT and is_publisher_active(
        user, application.project.ministry
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@require_POST
def application_withdraw(request: HttpRequest, application_id: int) -> HttpResponse:
    """DSC-007: withdraw an applicant's eligible application via the lifecycle service."""
    application = _visible_application_or_404(request.user, application_id)
    try:
        withdraw_application(request.user, application)
    except ApplicationAuthorizationError as error:
        raise PermissionDenied from error
    except ApplicationDecisionError:
        return render(
            request,
            "projects/application_timeline.html",
            _timeline_context(
                request,
                application,
                application.events.select_related("actor"),
                error=_("Unable to withdraw this application."),
            ),
            status=400,
        )
    return redirect("projects:application_timeline", application_id=application.pk)


@login_required(login_url=reverse_lazy("accounts:login"))
@require_POST
def application_provide_info(request: HttpRequest, application_id: int) -> HttpResponse:
    """DSC-007: add an applicant information response through the lifecycle service."""
    application = _visible_application_or_404(request.user, application_id)
    try:
        provide_info(request.user, application, request.POST.get("text", ""))
    except ApplicationAuthorizationError as error:
        raise PermissionDenied from error
    except ApplicationDecisionError:
        return render(
            request,
            "projects/application_timeline.html",
            _timeline_context(
                request,
                application,
                application.events.select_related("actor"),
                error=_("Information cannot be sent for this application."),
            ),
            status=400,
        )
    return redirect("projects:application_timeline", application_id=application.pk)


@login_required(login_url=reverse_lazy("accounts:login"))
@require_POST
def application_decide(request: HttpRequest, application_id: int) -> HttpResponse:
    """DSC-007: record an authorized publisher or Super Admin application decision."""
    application = _visible_application_or_404(request.user, application_id)
    try:
        decide_application(
            request.user,
            application,
            request.POST.get("decision", ""),
            note=request.POST.get("note", ""),
        )
    except ApplicationAuthorizationError as error:
        raise PermissionDenied from error
    except ApplicationDecisionError:
        decision_events = application.events.select_related("actor").filter(
            event__in=(ApplicationEventType.STATUS_CHANGED, ApplicationEventType.INFO_REQUESTED)
        )
        return render(
            request,
            "projects/application_detail.html",
            {
                "application": application,
                "decision_history": _decision_history(decision_events),
                "decision_choices": [
                    (decision, ApplicationStatus(decision).label)
                    for decision in ApplicationStatus
                    if decision in APPLICATION_DECISION_TRANSITIONS.get(application.status, set())
                ],
                "can_decide": _can_decide_application(request.user, application),
                "error": _("This decision is not available for the current application status."),
            },
            status=400,
        )
    return redirect("projects:application_detail", application_id=application.pk)


@login_required(login_url=reverse_lazy("accounts:login"))
@require_POST
def toggle_bookmark(request: HttpRequest, slug: str) -> HttpResponse:
    """DSC-004: member bookmark toggle with an opt-in change-notification preference."""
    project = get_object_or_404(public_projects(), slug=normalize_nfc(slug))
    bookmark = ProjectBookmark.objects.filter(user=request.user, project=project).first()
    if bookmark:
        bookmark.delete()
    else:
        ProjectBookmark.objects.create(
            user=request.user,
            project=project,
            notify_on_change=request.POST.get("notify_on_change") in {"1", "on", "true"},
        )
    return redirect("projects:detail", slug=project.slug)


@login_required(login_url=reverse_lazy("accounts:login"))
@require_POST
def apply(request: HttpRequest, slug: str) -> HttpResponse:
    """DSC-005/DSC-006: submit an application with project-owned screening answers."""
    project = get_object_or_404(public_project_details(), slug=normalize_nfc(slug))
    answers = [
        {"question_id": question.pk, "answer": request.POST.get(f"answer_{question.pk}", "")}
        for question in project.screening_questions.filter(is_active=True)
    ]
    try:
        apply_to_project(
            request.user,
            project,
            answers=answers,
            motivation=request.POST.get("motivation", ""),
        )
    except ApplicationError as error:
        return render(
            request,
            "projects/project_detail.html",
            public_project_detail_context(project, error=str(error)),
            status=400,
        )
    return redirect("projects:detail", slug=project.slug)
