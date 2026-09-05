"""Project lifecycle, review, readiness, and application services.

The government lifecycle state machine follows SRS 6.1 exactly; personal
listings run the PPR-001 subset. Every state-changing action is audited with
before/after provenance (GOV-005, SEC-008).
"""

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import PurePosixPath
from urllib.parse import quote, urlparse
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext

from apps.accounts.models import MemberProfile, MemberSkill
from apps.accounts.services import require_privileged_mfa
from apps.analytics.enums import EventName
from apps.analytics.services import AnalyticsError, record_event
from apps.audit.models import AuditEvent
from apps.audit.services import record_audit
from apps.contributions.enums import VerificationStatus
from apps.contributions.models import ContributionRecord
from apps.github_sync.enums import SyncState
from apps.github_sync.models import GithubConnection, RepositoryConnection
from apps.ministries.models import MinistryPublisher
from apps.ministries.services import is_publisher_active
from apps.notifications.enums import NotificationType
from apps.notifications.services import notify
from apps.projects.enums import (
    ApplicationEventType,
    ApplicationStatus,
    OwnershipVerificationStatus,
    ParticipationKind,
    ProjectStatus,
    ProjectType,
    ResponseSla,
    ReviewDecision,
    ScanStatus,
)
from apps.projects.models import (
    SUITABILITY_AREAS,
    Application,
    ApplicationEvent,
    CommunityTermsAcceptance,
    Project,
    ProjectAttachment,
    ProjectBookmark,
    ProjectMaintainer,
    ProjectMilestone,
    ProjectReview,
    ProjectReviewAssignment,
    ProjectScreeningQuestion,
    ProjectSuitability,
    ProjectTask,
    ProjectUpdate,
    ProjectVersion,
)
from apps.taxonomy.fields import normalize_nfc

logger = logging.getLogger(__name__)

TRANSITIONS: dict[str, set[str]] = {
    ProjectStatus.DRAFT: {ProjectStatus.IN_REVIEW},
    ProjectStatus.IN_REVIEW: {
        ProjectStatus.CHANGES_REQUESTED,
        ProjectStatus.APPROVED,
        ProjectStatus.DRAFT,
    },
    ProjectStatus.CHANGES_REQUESTED: {ProjectStatus.IN_REVIEW},
    ProjectStatus.APPROVED: {
        ProjectStatus.OPEN_FOR_CONTRIBUTION,
        ProjectStatus.CHANGES_REQUESTED,
    },
    ProjectStatus.OPEN_FOR_CONTRIBUTION: {
        ProjectStatus.PAUSED,
        ProjectStatus.COMPLETED,
        ProjectStatus.CANCELLED,
        ProjectStatus.ARCHIVED,
    },
    ProjectStatus.PAUSED: {
        ProjectStatus.OPEN_FOR_CONTRIBUTION,
        ProjectStatus.COMPLETED,
        ProjectStatus.CANCELLED,
        ProjectStatus.ARCHIVED,
    },
    ProjectStatus.COMPLETED: {ProjectStatus.ARCHIVED, ProjectStatus.OPEN_FOR_CONTRIBUTION},
    ProjectStatus.CANCELLED: {ProjectStatus.ARCHIVED, ProjectStatus.OPEN_FOR_CONTRIBUTION},
    ProjectStatus.ARCHIVED: set(),
}

PERSONAL_TRANSITIONS: dict[str, set[str]] = {
    ProjectStatus.DRAFT: {ProjectStatus.OPEN_FOR_CONTRIBUTION},
    ProjectStatus.OPEN_FOR_CONTRIBUTION: {
        ProjectStatus.DRAFT,
        ProjectStatus.PAUSED,
        ProjectStatus.COMPLETED,
        ProjectStatus.CANCELLED,
        ProjectStatus.ARCHIVED,
    },
    ProjectStatus.PAUSED: {
        ProjectStatus.OPEN_FOR_CONTRIBUTION,
        ProjectStatus.COMPLETED,
        ProjectStatus.CANCELLED,
        ProjectStatus.ARCHIVED,
    },
    ProjectStatus.COMPLETED: {ProjectStatus.ARCHIVED},
    ProjectStatus.CANCELLED: {ProjectStatus.ARCHIVED},
    ProjectStatus.IN_REVIEW: set(),
    ProjectStatus.CHANGES_REQUESTED: set(),
    ProjectStatus.APPROVED: set(),
    ProjectStatus.ARCHIVED: set(),
}

RESTORE_TARGETS = {
    ProjectStatus.OPEN_FOR_CONTRIBUTION,
    ProjectStatus.PAUSED,
    ProjectStatus.COMPLETED,
    ProjectStatus.CANCELLED,
}

MATERIAL_EDIT_FIELDS = [
    "license",
    "license_id",
    "repository_url",
    "data_classification",
    "description_md",
    "problem_statement",
    "signoff_model",
    "security_contact",
    "communication_channel",
]

EDITABLE_STATES = {
    ProjectStatus.DRAFT,
    ProjectStatus.CHANGES_REQUESTED,
    ProjectStatus.OPEN_FOR_CONTRIBUTION,
    ProjectStatus.PAUSED,
}

MATERIAL_EDIT_REVIEW_STATES = {
    ProjectStatus.OPEN_FOR_CONTRIBUTION,
    ProjectStatus.PAUSED,
}

APPLICATION_BLOCKED_STATES = {
    ProjectStatus.PAUSED,
    ProjectStatus.COMPLETED,
    ProjectStatus.CANCELLED,
    ProjectStatus.ARCHIVED,
}

APPLICATION_DECISION_TRANSITIONS = {
    ApplicationStatus.SUBMITTED: {
        ApplicationStatus.ACCEPTED,
        ApplicationStatus.WAITLISTED,
        ApplicationStatus.DECLINED,
        ApplicationStatus.INFO_REQUESTED,
    },
    ApplicationStatus.INFO_REQUESTED: {
        ApplicationStatus.ACCEPTED,
        ApplicationStatus.WAITLISTED,
        ApplicationStatus.DECLINED,
    },
    ApplicationStatus.WAITLISTED: {ApplicationStatus.ACCEPTED, ApplicationStatus.DECLINED},
    ApplicationStatus.ACCEPTED: set(),
    ApplicationStatus.DECLINED: set(),
    ApplicationStatus.WITHDRAWN: set(),
}

BLOCKED_ATTACHMENT_SUFFIXES = {
    ".exe",
    ".dll",
    ".com",
    ".bat",
    ".cmd",
    ".sh",
    ".msi",
    ".scr",
    ".ps1",
    ".jar",
    ".app",
    ".svg",
}

SNAPSHOT_EXCLUDED_FIELDS = {"id", "created_at", "updated_at", "status_changed_at"}


class ProjectLifecycleError(Exception):
    """An SRS 6.1 lifecycle rule was violated."""


class SubmissionReadinessError(ProjectLifecycleError):
    """A draft is not complete enough to enter review (GOV-002, 14.3)."""


class PublishReadinessError(ProjectLifecycleError):
    """BR-002/BR-003/GOV-007 publication gates are unmet."""

    def __init__(self, violations):
        self.violations = list(violations)
        super().__init__("publication blocked: " + ", ".join(self.violations))


class CompletionSummaryError(ProjectLifecycleError):
    """Required structured closure evidence is missing or invalid (GOV-009/A14)."""


class ProjectAuthorizationError(Exception):
    """The actor may not perform this action on this project (GOV-001, AUTH-006)."""


class MaterialEditError(ProjectLifecycleError):
    """An edit was rejected (unknown field or closed record) (GOV-006)."""


class ApplicationError(Exception):
    """An application could not be created (DSC-005, DSC-006)."""


class ApplicationClosedError(ApplicationError):
    """The project does not accept new applications (BR-011)."""


class ApplicationAuthorizationError(Exception):
    """The actor may not decide or view this application (DSC-007, DSC-008)."""


class ApplicationDecisionError(ApplicationError):
    """An illegal application status transition (DSC-007)."""


class ApplicationAnalyticsError(ApplicationError):
    """A successful application could not persist its required ANL-001 event."""


class GitHubVerificationError(Exception):
    """The GitHub repository lookup could not complete (PPR-004)."""


COMMUNITY_TERMS_VERSION = "2026.09"

RESPONSE_SLA_DAYS = {
    ResponseSla.WITHIN_24_HOURS: 1,
    ResponseSla.WITHIN_3_DAYS: 3,
    ResponseSla.WITHIN_1_WEEK: 7,
}

DEMO_REPOSITORY_FULL_NAME = "voidash/civic-help-directory"


class AttachmentError(Exception):
    """An upload failed validation (GOV-003, SEC-007)."""


def _is_super_admin(actor) -> bool:
    return bool(
        actor
        and getattr(actor, "is_active", False)
        and getattr(actor, "is_authenticated", False)
        and getattr(actor, "is_superuser", False)
    )


def _require_super_admin(actor, *, action: str, obj=None) -> None:
    if _is_super_admin(actor):
        require_privileged_mfa(actor, action=action, obj=obj, error_type=ProjectAuthorizationError)
        return
    record_audit(actor=actor, action=f"{action}.denied", obj=obj, result="failure")
    raise ProjectAuthorizationError(f"{action} requires an active Super Admin")


def _require_publisher(actor, project: Project, *, action: str) -> None:
    if project.project_type == ProjectType.PERSONAL:
        if actor and actor.is_active and project.owner_id == actor.pk:
            return
    elif _is_super_admin(actor):
        require_privileged_mfa(
            actor, action=action, obj=project, error_type=ProjectAuthorizationError
        )
        return
    elif is_publisher_active(actor, project.ministry):
        require_privileged_mfa(
            actor, action=action, obj=project, error_type=ProjectAuthorizationError
        )
        return
    record_audit(actor=actor, action=f"{action}.denied", obj=project, result="failure")
    raise ProjectAuthorizationError(
        f"{action} requires an active publisher of the owning ministry (GOV-001)"
    )


def _require_owner_or_super_admin(actor, project: Project, *, action: str) -> None:
    if _is_super_admin(actor):
        require_privileged_mfa(
            actor, action=action, obj=project, error_type=ProjectAuthorizationError
        )
        return
    _require_publisher(actor, project, action=action)


def _transitions_for(project: Project) -> dict[str, set[str]]:
    if project.project_type == ProjectType.PERSONAL:
        return PERSONAL_TRANSITIONS
    return TRANSITIONS


def _audit_transition(actor, project: Project, action: str, before: dict, after: dict) -> None:
    record_audit(actor=actor, action=f"project.{action}", obj=project, before=before, after=after)


def _status_payload(project: Project, **extra) -> dict:
    payload = {"status": project.status}
    payload.update(extra)
    return payload


def snapshot_project(project: Project) -> dict:
    """Serialize every Appendix A field of the current state (A2, GOV-005)."""
    data = {}
    for field in project._meta.concrete_fields:
        if field.name in SNAPSHOT_EXCLUDED_FIELDS:
            continue
        value = getattr(project, field.attname)
        if isinstance(value, datetime):
            value = value.isoformat()
        elif isinstance(value, date):
            value = value.isoformat()
        elif isinstance(value, uuid.UUID):
            value = str(value)
        data[field.name] = value
    for m2m in project._meta.many_to_many:
        data[m2m.name] = sorted(getattr(project, m2m.name).values_list("pk", flat=True))
    return data


def _latest_version(project: Project) -> ProjectVersion | None:
    return project.versions.order_by("-version_number").first()


def _next_version_number(project: Project) -> int:
    latest = _latest_version(project)
    return (latest.version_number + 1) if latest else 1


def create_version(project: Project, submitted_by) -> ProjectVersion:
    with transaction.atomic():
        version = ProjectVersion.objects.create(
            project=project,
            version_number=_next_version_number(project),
            snapshot=snapshot_project(project),
            submitted_by=submitted_by,
        )
    return version


def _review_row(
    project: Project,
    reviewer,
    decision: str,
    *,
    comment: str,
    from_status: str,
    to_status: str,
) -> ProjectReview:
    version = _latest_version(project)
    if version is None:
        raise ProjectLifecycleError("no submission version exists to attach the review decision to")
    return ProjectReview.objects.create(
        project=project,
        version=version,
        reviewer=reviewer,
        decision=decision,
        comment=comment,
        from_status=from_status,
        to_status=to_status,
    )


def _perform_transition(
    project: Project,
    to_status: str,
    *,
    actor,
    action: str,
    allowed_override: bool = False,
    extra_after: dict | None = None,
) -> Project:
    before_status = project.status
    if not allowed_override and to_status not in _transitions_for(project).get(
        before_status, set()
    ):
        raise ProjectLifecycleError(
            f"transition from '{before_status}' to '{to_status}' is not allowed "
            f"by the SRS 6.1 lifecycle"
        )
    now = timezone.now()
    project.status = to_status
    project.status_changed_at = now
    update_fields = ["status", "status_changed_at"]
    if to_status == ProjectStatus.ARCHIVED:
        project.archived_at = now
        update_fields.append("archived_at")
    project.save(update_fields=update_fields)
    after = _status_payload(project)
    if extra_after:
        after.update(extra_after)
    _audit_transition(
        actor,
        project,
        action,
        _status_payload(project, status=before_status),
        after,
    )
    return project


def _schedule_notification(recipient, type_: str, context_url: str, dedup_key: str) -> None:
    if recipient is None or not getattr(recipient, "is_active", False):
        return

    def dispatch() -> None:
        try:
            notify(recipient, type_, {"context_url": context_url}, dedup_key=dedup_key)
        except Exception:
            logger.exception(
                "notification delivery setup failed; recipient=%s type=%s dedup_key=%s",
                recipient.pk,
                type_,
                dedup_key,
            )

    transaction.on_commit(dispatch)


def _schedule_review_notifications(project: Project, review: ProjectReview) -> None:
    type_ = (
        NotificationType.REVIEW_COMMENT
        if review.decision in {"changes_requested", "revoked"}
        else NotificationType.REVIEW_DECISION
    )
    _schedule_notification(
        project.owner,
        type_,
        f"/authoring/{project.slug}/manage/",
        f"project:{project.pk}:review:{review.pk}",
    )


def _schedule_review_queue_notifications(project: Project, version: ProjectVersion) -> None:
    from django.contrib.auth import get_user_model

    for reviewer in get_user_model().objects.filter(is_active=True, is_superuser=True):
        _schedule_notification(
            reviewer,
            NotificationType.REVIEW_DECISION,
            f"/authoring/{project.slug}/manage/",
            f"project:{project.pk}:submission:{version.pk}",
        )


def _schedule_publication_notifications(project: Project, version: ProjectVersion) -> None:
    dedup_key = f"project:{project.pk}:published:{version.pk}"
    _schedule_notification(
        project.owner,
        NotificationType.PROJECT_STATUS,
        f"/projects/{project.slug}/",
        dedup_key,
    )
    for bookmark in project.bookmarks.filter(notify_on_change=True).select_related("user"):
        _schedule_notification(
            bookmark.user,
            NotificationType.PROJECT_STATUS,
            f"/projects/{project.slug}/",
            dedup_key,
        )


def _application_recipients(application: Application):
    project = application.project
    if project.project_type == ProjectType.PERSONAL:
        return [project.owner]
    return [
        publisher.user
        for publisher in MinistryPublisher.objects.filter(
            ministry=project.ministry,
            status="active",
            ministry__status="active",
            user__is_active=True,
        ).select_related("user")
    ]


def _schedule_application_submission_notifications(
    application: Application, event: ApplicationEvent
) -> None:
    recipients = {recipient.pk: recipient for recipient in _application_recipients(application)}
    recipients.pop(application.applicant_id, None)
    for recipient in recipients.values():
        _schedule_notification(
            recipient,
            NotificationType.APPLICATION_STATUS,
            f"/applications/{application.pk}/",
            f"application:{application.pk}:event:{event.pk}:recipient:{recipient.pk}",
        )


def _schedule_application_decision_notification(
    application: Application, event: ApplicationEvent
) -> None:
    _schedule_notification(
        application.applicant,
        NotificationType.APPLICATION_STATUS,
        f"/applications/{application.pk}/",
        f"application:{application.pk}:event:{event.pk}",
    )


# ---------------------------------------------------------------------------
# Draft access (GOV-001)


def drafts_for_publisher(user):
    ministries = MinistryPublisher.objects.filter(
        user=user, status="active", ministry__status="active"
    ).values_list("ministry_id", flat=True)
    return Project.objects.filter(
        project_type=ProjectType.GOVERNMENT, ministry__in=ministries, status=ProjectStatus.DRAFT
    )


def projects_for_publisher(user):
    ministries = MinistryPublisher.objects.filter(
        user=user, status="active", ministry__status="active"
    ).values_list("ministry_id", flat=True)
    return Project.objects.filter(project_type=ProjectType.GOVERNMENT, ministry__in=ministries)


def create_government_draft(actor, ministry, **fields) -> Project:
    """GOV-001/GOV-002: create a ministry-scoped government draft with an attributable owner."""
    if _is_super_admin(actor):
        require_privileged_mfa(
            actor, action="project.create", obj=ministry, error_type=ProjectAuthorizationError
        )
    elif is_publisher_active(actor, ministry):
        require_privileged_mfa(
            actor, action="project.create", obj=ministry, error_type=ProjectAuthorizationError
        )
    else:
        record_audit(actor=actor, action="project.create.denied", obj=ministry, result="failure")
        raise ProjectAuthorizationError(
            "project.create requires an active publisher of the selected ministry (GOV-001)"
        )

    title = fields.get("title_en", "")
    base_slug = slugify(title, allow_unicode=True) or "government-project"
    slug = base_slug
    suffix = 2
    while Project.objects.filter(slug=slug).exists():
        slug = f"{base_slug}-{suffix}"
        suffix += 1

    project = Project.objects.create(
        project_type=ProjectType.GOVERNMENT,
        ministry=ministry,
        owner=actor,
        slug=slug,
        **fields,
    )
    record_audit(
        actor=actor,
        action="project.draft_created",
        obj=project,
        after={"status": project.status, "ministry_id": ministry.pk},
    )
    return project


def reusable_bound_project_for_demo(actor, ministry, repository_url: str) -> Project | None:
    """GOV-001/GOV-002/GIT-003: reuse the canonical connected demo project safely.

    The demo helper is intentionally idempotent. It must never duplicate a
    repository connection or redirect across ministry authorization boundaries.
    """
    repository_name = parse_github_repo_slug(repository_url)
    if repository_name is None or repository_name.casefold() != DEMO_REPOSITORY_FULL_NAME:
        return None

    connection = (
        RepositoryConnection.objects.filter(
            full_name__iexact=repository_name,
            is_public=True,
            deactivated_at__isnull=True,
            project__isnull=False,
        )
        .exclude(sync_state=SyncState.STOPPED)
        .select_related("project__ministry")
        .first()
    )
    if connection is None:
        return None

    project = connection.project
    if project.project_type != ProjectType.GOVERNMENT or project.ministry_id != ministry.pk:
        record_audit(
            actor=actor,
            action="project.demo_reuse.denied",
            obj=ministry,
            result="failure",
        )
        raise ProjectAuthorizationError("the prepared demo project is unavailable")
    _require_publisher(actor, project, action="project.demo_reuse")
    return project


def create_personal_draft(owner, **fields) -> Project:
    """PPR-001/PPR-002: create a member-owned community listing without a ministry."""
    if not (owner and owner.is_authenticated and owner.is_active):
        raise ProjectAuthorizationError("project.create requires an active member account")

    base_slug = slugify(fields.get("title_en", ""), allow_unicode=True) or "community-project"
    slug = base_slug
    suffix = 2
    while Project.objects.filter(slug=slug).exists():
        slug = f"{base_slug}-{suffix}"
        suffix += 1

    project = Project.objects.create(
        project_type=ProjectType.PERSONAL,
        owner=owner,
        slug=slug,
        **fields,
    )
    record_audit(
        actor=owner,
        action="project.personal_draft_created",
        obj=project,
        after={"status": project.status, "owner_id": owner.pk},
    )
    return project


# ---------------------------------------------------------------------------
# Government lifecycle (GOV-004)


def submit_for_review(publisher, project: Project) -> Project:
    """GOV-004/GOV-002: publisher submits a complete bilingual draft for review."""
    _require_publisher(publisher, project, action="project.submit")
    if project.project_type == ProjectType.PERSONAL:
        raise ProjectLifecycleError(
            "personal projects never enter review; publish them directly (PPR-001)"
        )
    missing = [
        field
        for field in ("title_en", "title_ne", "summary_en", "summary_ne")
        if not getattr(project, field).strip()
    ]
    if missing:
        raise SubmissionReadinessError(
            "government submission requires bilingual title and summary; missing: "
            + ", ".join(missing)
        )
    version = create_version(project, submitted_by=publisher)
    transitioned = _perform_transition(
        project, ProjectStatus.IN_REVIEW, actor=publisher, action="submitted"
    )
    _schedule_review_queue_notifications(project, version)
    return transitioned


def assign_reviewer(
    super_admin,
    project: Project,
    *,
    reviewer,
    due_at: datetime,
    reviewer_note: str = "",
    checklist: dict | None = None,
) -> ProjectReviewAssignment:
    """ADM-002/GOV-005: assign the current immutable submission to one PMO reviewer."""
    _require_super_admin(super_admin, action="project.assign_reviewer", obj=project)
    if project.status != ProjectStatus.IN_REVIEW:
        raise ProjectLifecycleError("reviewer assignment requires an in-review project")
    if reviewer is None or not reviewer.is_active or not reviewer.is_superuser:
        raise ProjectLifecycleError("reviewer must be an active Super Admin")
    if due_at is None or timezone.is_naive(due_at) or due_at <= timezone.now():
        raise ProjectLifecycleError("review due date must be in the future")
    version = _latest_version(project)
    if version is None:
        raise ProjectLifecycleError("reviewer assignment requires a submitted version")
    checklist = checklist or {}
    invalid = set(checklist) - set(SUITABILITY_AREAS)
    if invalid or any(not isinstance(value, bool) for value in checklist.values()):
        raise ProjectLifecycleError("review checklist contains invalid items")
    with transaction.atomic():
        current = (
            ProjectReviewAssignment.objects.select_for_update().filter(project=project).first()
        )
        before = (
            {
                "version": str(current.version_id),
                "reviewer_id": current.reviewer_id,
                "due_at": current.due_at.isoformat(),
                "reviewer_note": current.reviewer_note,
                "checklist": current.checklist,
            }
            if current
            else None
        )
        assignment, _created = ProjectReviewAssignment.objects.update_or_create(
            project=project,
            defaults={
                "version": version,
                "reviewer": reviewer,
                "assigned_by": super_admin,
                "due_at": due_at,
                "reviewer_note": normalize_nfc(reviewer_note).strip(),
                "checklist": checklist,
            },
        )
        record_audit(
            actor=super_admin,
            action="project.reviewer_assigned",
            obj=project,
            before=before,
            after={
                "version": str(version.pk),
                "reviewer_id": reviewer.pk,
                "due_at": due_at.isoformat(),
                "reviewer_note": assignment.reviewer_note,
                "checklist": checklist,
            },
        )
    return assignment


def _require_assigned_reviewer(super_admin, project: Project) -> None:
    assignment = ProjectReviewAssignment.objects.filter(
        project=project, version=_latest_version(project)
    ).first()
    if assignment is not None and assignment.reviewer_id != super_admin.pk:
        record_audit(
            actor=super_admin,
            action="project.review_decision.denied",
            obj=project,
            result="failure",
        )
        raise ProjectAuthorizationError("only the assigned reviewer may decide this submission")


def request_changes(super_admin, project: Project, *, reason: str) -> Project:
    """GOV-004/GOV-005: Super Admin returns an in-review project with actionable comments."""
    _require_super_admin(super_admin, action="project.request_changes", obj=project)
    _require_assigned_reviewer(super_admin, project)
    if project.status != ProjectStatus.IN_REVIEW:
        raise ProjectLifecycleError(
            f"transition from '{project.status}' to '{ProjectStatus.CHANGES_REQUESTED}' "
            f"is not allowed by the SRS 6.1 lifecycle"
        )
    if not (reason or "").strip():
        raise ProjectLifecycleError("request_changes requires a non-empty reason")
    before_status = project.status
    review = _review_row(
        project,
        super_admin,
        "changes_requested",
        comment=reason,
        from_status=before_status,
        to_status=ProjectStatus.CHANGES_REQUESTED,
    )
    transitioned = _perform_transition(
        project,
        ProjectStatus.CHANGES_REQUESTED,
        actor=super_admin,
        action="changes_requested",
        extra_after={"version": str(_latest_version(project).pk)},
    )
    _schedule_review_notifications(project, review)
    return transitioned


def reject_submission(super_admin, project: Project, *, reason: str) -> Project:
    """GOV-004/GOV-005: rejection returns the project to DRAFT with the decision recorded."""
    _require_super_admin(super_admin, action="project.reject", obj=project)
    _require_assigned_reviewer(super_admin, project)
    if project.status != ProjectStatus.IN_REVIEW:
        raise ProjectLifecycleError(
            f"transition from '{project.status}' to '{ProjectStatus.DRAFT}' "
            f"is not allowed by the SRS 6.1 lifecycle"
        )
    if not (reason or "").strip():
        raise ProjectLifecycleError("rejection requires a non-empty reason")
    review = _review_row(
        project,
        super_admin,
        "rejected",
        comment=reason,
        from_status=project.status,
        to_status=ProjectStatus.DRAFT,
    )
    transitioned = _perform_transition(
        project,
        ProjectStatus.DRAFT,
        actor=super_admin,
        action="rejected",
        extra_after={"version": str(_latest_version(project).pk)},
    )
    _schedule_review_notifications(project, review)
    return transitioned


def resubmit(publisher, project: Project) -> Project:
    """GOV-004/GOV-006: the publisher edits and resubmits a changes-requested project."""
    _require_publisher(publisher, project, action="project.resubmit")
    if project.status != ProjectStatus.CHANGES_REQUESTED:
        raise ProjectLifecycleError(
            f"transition from '{project.status}' to '{ProjectStatus.IN_REVIEW}' "
            f"is not allowed by the SRS 6.1 lifecycle"
        )
    version = create_version(project, submitted_by=publisher)
    transitioned = _perform_transition(
        project, ProjectStatus.IN_REVIEW, actor=publisher, action="resubmitted"
    )
    _schedule_review_queue_notifications(project, version)
    return transitioned


def approve(
    super_admin,
    project: Project,
    *,
    publish_at: datetime | None = None,
    comment: str = "",
) -> Project:
    """GOV-004/GOV-005: Super Admin approves, optionally scheduling a future publication."""
    _require_super_admin(super_admin, action="project.approve", obj=project)
    _require_assigned_reviewer(super_admin, project)
    if project.status != ProjectStatus.IN_REVIEW:
        raise ProjectLifecycleError(
            f"transition from '{project.status}' to '{ProjectStatus.APPROVED}' "
            f"is not allowed by the SRS 6.1 lifecycle"
        )
    if publish_at is not None and (timezone.is_naive(publish_at) or publish_at <= timezone.now()):
        raise ProjectLifecycleError("scheduled publication must be a timezone-aware future time")
    before_status = project.status
    with transaction.atomic():
        review = _review_row(
            project,
            super_admin,
            "approved",
            comment=normalize_nfc(comment).strip(),
            from_status=before_status,
            to_status=ProjectStatus.APPROVED,
        )
        if publish_at is not None:
            project.scheduled_publication_at = publish_at
            project.save(update_fields=["scheduled_publication_at"])
        transitioned = _perform_transition(
            project,
            ProjectStatus.APPROVED,
            actor=super_admin,
            action="approved",
            extra_after={"version": str(_latest_version(project).pk)},
        )
    _schedule_review_notifications(project, review)
    return transitioned


def revoke_approval(super_admin, project: Project, *, reason: str) -> Project:
    """GOV-004/GOV-005: revoking approval returns the project to CHANGES_REQUESTED."""
    _require_super_admin(super_admin, action="project.revoke_approval", obj=project)
    _require_assigned_reviewer(super_admin, project)
    if project.status != ProjectStatus.APPROVED:
        raise ProjectLifecycleError(
            f"transition from '{project.status}' to '{ProjectStatus.CHANGES_REQUESTED}' "
            f"is not allowed by the SRS 6.1 lifecycle"
        )
    if not (reason or "").strip():
        raise ProjectLifecycleError("revoking approval requires a non-empty reason")
    review = _review_row(
        project,
        super_admin,
        "revoked",
        comment=reason,
        from_status=project.status,
        to_status=ProjectStatus.CHANGES_REQUESTED,
    )
    project.scheduled_publication_at = None
    project.save(update_fields=["scheduled_publication_at"])
    transitioned = _perform_transition(
        project,
        ProjectStatus.CHANGES_REQUESTED,
        actor=super_admin,
        action="approval_revoked",
    )
    _schedule_review_notifications(project, review)
    return transitioned


def check_publish_readiness(project: Project) -> list[str]:
    """Return named BR-002/BR-003/GOV-007 publication violations (empty list = ready).

    BR-002: named ministry owner, public maintainer/contact path, approved
    contribution mode, response expectation, suitability confirmation.
    GOV-007: instructions (prerequisites), difficulty, effort, actionable task.
    BR-003: approved license plus repository readiness (README, issue entry,
    branch controls, code of conduct, security path, readiness attestation).
    GOV-003: no quarantined or failed attachment.
    """
    violations: list[str] = []

    if project.project_type != ProjectType.GOVERNMENT:
        return ["government_project_required"]

    if project.ministry_id is None:
        violations.append("ministry_owner_missing")
    if not project.maintainer_assignments.exists():
        violations.append("maintainer_missing")
    if not project.communication_channel:
        violations.append("contact_channel_missing")
    if not project.contribution_mode:
        violations.append("contribution_mode_missing")
    if not project.response_sla:
        violations.append("response_expectation_missing")

    suitability = ProjectSuitability.objects.filter(project=project).first()
    if suitability is None or suitability.confirmed_at is None:
        violations.append("suitability_not_confirmed")
    elif not suitability.checklist.get("repository_readiness", {}).get("checked", False):
        violations.append("repository_readiness_unconfirmed")

    if not project.prerequisites:
        violations.append("instructions_missing")
    if not project.difficulty:
        violations.append("difficulty_missing")
    if not project.estimated_effort:
        violations.append("effort_missing")
    if not ProjectTask.objects.filter(project=project).exclude(status="cancelled").exists():
        violations.append("task_missing")

    if project.license_id is None:
        violations.append("license_missing")
    elif not project.license.is_approved:
        violations.append("license_not_approved")
    if not project.repository_url:
        violations.append("repository_url_missing")
    else:
        from apps.github_sync.enums import SyncState

        repository_name = parse_github_repo_slug(project.repository_url)
        has_active_connection = bool(
            repository_name
            and project.repository_connections.filter(
                full_name__iexact=repository_name,
                deactivated_at__isnull=True,
            )
            .exclude(sync_state=SyncState.STOPPED)
            .exists()
        )
        if not has_active_connection:
            violations.append("repository_connection_missing")
    if not project.documentation_url:
        violations.append("readme_missing")
    if not project.code_of_conduct_url:
        violations.append("code_of_conduct_missing")
    if not project.security_contact and not project.vulnerability_disclosure_url:
        violations.append("security_path_missing")
    if not project.issue_tracker_url:
        violations.append("issue_entry_missing")
    if not project.default_branch:
        violations.append("branch_controls_missing")

    if project.attachments.filter(scan__in=[ScanStatus.QUARANTINED, ScanStatus.FAILED]).exists():
        violations.append("attachment_quarantined")

    return violations


def publish(super_admin, project: Project, *, comment: str = "") -> Project:
    """GOV-004/BR-002: publish an approved project, serving exactly the approved version."""
    _require_super_admin(super_admin, action="project.publish", obj=project)
    if project.status != ProjectStatus.APPROVED:
        raise ProjectLifecycleError(
            f"transition from '{project.status}' to '{ProjectStatus.OPEN_FOR_CONTRIBUTION}' "
            f"is not allowed by the SRS 6.1 lifecycle"
        )
    violations = check_publish_readiness(project)
    if violations:
        raise PublishReadinessError(violations)
    version = _latest_version(project)
    if version is None:
        raise ProjectLifecycleError("cannot publish without an approved submission version")

    before_status = project.status
    now = timezone.now()
    project.status = ProjectStatus.OPEN_FOR_CONTRIBUTION
    project.status_changed_at = now
    project.published_at = now
    project.current_version = version
    project.scheduled_publication_at = None
    project.save(
        update_fields=[
            "status",
            "status_changed_at",
            "published_at",
            "current_version",
            "scheduled_publication_at",
        ]
    )
    version.published_at = now
    version.published_by = super_admin
    version.save(update_fields=["published_at", "published_by"])
    _review_row(
        project,
        super_admin,
        "published",
        comment=normalize_nfc(comment).strip(),
        from_status=before_status,
        to_status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
    )
    _audit_transition(
        super_admin,
        project,
        "published",
        _status_payload(project, status=before_status),
        _status_payload(project, version=str(version.pk)),
    )
    _schedule_publication_notifications(project, version)
    return project


def publish_by_publisher(publisher, project: Project) -> Project:
    """GOV-001/GOV-004: let the owning ministry publish a GitHub-backed draft directly."""
    _require_publisher(publisher, project, action="project.publisher_publish")
    if project.project_type != ProjectType.GOVERNMENT:
        raise ProjectLifecycleError("direct ministry publication requires a government project")

    with transaction.atomic():
        locked = Project.objects.select_for_update().get(pk=project.pk)
        if locked.status != ProjectStatus.DRAFT:
            raise ProjectLifecycleError("only a ministry draft can be published directly")
        violations = _publisher_publish_readiness(locked)
        if violations:
            raise PublishReadinessError(violations)

        version = create_version(locked, submitted_by=publisher)
        now = timezone.now()
        before_status = locked.status
        locked.status = ProjectStatus.OPEN_FOR_CONTRIBUTION
        locked.status_changed_at = now
        locked.published_at = now
        locked.current_version = version
        locked.save(
            update_fields=["status", "status_changed_at", "published_at", "current_version"]
        )
        version.published_at = now
        version.published_by = publisher
        version.save(update_fields=["published_at", "published_by"])
        _review_row(
            locked,
            publisher,
            ReviewDecision.PUBLISHED,
            comment="Published by the owning ministry",
            from_status=before_status,
            to_status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
        )
        _audit_transition(
            publisher,
            locked,
            "publisher_published",
            _status_payload(locked, status=before_status),
            _status_payload(locked, version=str(version.pk)),
        )

    _schedule_publication_notifications(locked, version)
    return locked


def _publisher_publish_readiness(project: Project) -> list[str]:
    """GOV-004/GIT-010: require public repository proof without PMO-only ceremony."""
    violations = []
    for field in ("title_en", "title_ne", "summary_en", "summary_ne"):
        if not getattr(project, field, "").strip():
            violations.append(f"{field}_missing")
    if project.license_id is None or not project.license.is_approved:
        violations.append("approved_license_missing")
    repository_name = parse_github_repo_slug(project.repository_url)
    connection = (
        project.repository_connections.filter(
            full_name__iexact=repository_name or "",
            deactivated_at__isnull=True,
            is_public=True,
        )
        .exclude(sync_state="stopped")
        .first()
    )
    if connection is None:
        violations.append("public_repository_connection_missing")
    for field in ("default_branch", "issue_tracker_url", "documentation_url"):
        if not getattr(project, field, "").strip():
            violations.append(f"{field}_missing")
    return violations


def publish_due_scheduled(now: datetime | None = None) -> list[Project]:
    """GOV-004: scheduled publications open when their date arrives (system actor)."""
    moment = now or timezone.now()
    due = Project.objects.filter(
        project_type=ProjectType.GOVERNMENT,
        status=ProjectStatus.APPROVED,
        scheduled_publication_at__lte=moment,
    )
    published_projects = []
    for project in due:
        try:
            published_projects.append(_publish_system(project))
        except ProjectLifecycleError:
            logger.exception(
                "scheduled publication failed; project=%s status=%s", project.pk, project.status
            )
    return published_projects


def _publish_system(project: Project) -> Project:
    violations = check_publish_readiness(project)
    if violations:
        raise PublishReadinessError(violations)
    version = _latest_version(project)
    if version is None:
        raise ProjectLifecycleError("cannot publish without an approved submission version")
    before_status = project.status
    now = timezone.now()
    project.status = ProjectStatus.OPEN_FOR_CONTRIBUTION
    project.status_changed_at = now
    project.published_at = now
    project.current_version = version
    project.scheduled_publication_at = None
    project.save(
        update_fields=[
            "status",
            "status_changed_at",
            "published_at",
            "current_version",
            "scheduled_publication_at",
        ]
    )
    version.published_at = now
    version.save(update_fields=["published_at"])
    _audit_transition(
        None,
        project,
        "published",
        _status_payload(project, status=before_status),
        _status_payload(project, version=str(version.pk)),
    )
    _schedule_publication_notifications(project, version)
    return project


def pause(actor, project: Project) -> Project:
    """GOV-004/PPR-001: owner or Super Admin pauses; status stays publicly visible."""
    _require_owner_or_super_admin(actor, project, action="project.pause")
    return _perform_transition(project, ProjectStatus.PAUSED, actor=actor, action="paused")


def resume(actor, project: Project) -> Project:
    """GOV-004/PPR-001: a paused project resumes accepting participation."""
    _require_owner_or_super_admin(actor, project, action="project.resume")
    if project.status in {ProjectStatus.COMPLETED, ProjectStatus.CANCELLED}:
        raise ProjectLifecycleError(
            "completed or cancelled projects reopen only by approval (reopen, Super Admin)"
        )
    return _perform_transition(
        project, ProjectStatus.OPEN_FOR_CONTRIBUTION, actor=actor, action="resumed"
    )


def _normalize_deliverables(deliverables) -> list[dict[str, str]]:
    if not isinstance(deliverables, list) or not deliverables:
        raise CompletionSummaryError(gettext("deliverables must contain at least one item"))
    if len(deliverables) > 50:
        raise CompletionSummaryError(gettext("deliverables cannot contain more than 50 items"))
    normalized = []
    for index, item in enumerate(deliverables, start=1):
        if not isinstance(item, dict):
            raise CompletionSummaryError(
                gettext("deliverable %(index)s must contain a label and optional URL")
                % {"index": index}
            )
        label = normalize_nfc(item.get("label", ""))
        url = normalize_nfc(item.get("url", ""))
        if not label or len(label) > 200:
            raise CompletionSummaryError(
                gettext("deliverable %(index)s needs a label of 200 characters or fewer")
                % {"index": index}
            )
        parsed_url = urlparse(url) if url else None
        if url and (parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc):
            raise CompletionSummaryError(
                gettext("deliverable %(index)s must use an HTTP or HTTPS URL") % {"index": index}
            )
        normalized.append({"label": label, "url": url})
    return normalized


def _validated_completion_summary(
    *, outcome_summary, deliverables, impact_summary, lessons_learned
) -> dict:
    values = {
        "outcome_summary": normalize_nfc(outcome_summary),
        "deliverables": deliverables,
        "impact_summary": normalize_nfc(impact_summary),
        "lessons_learned": normalize_nfc(lessons_learned),
    }
    missing = [
        label
        for field, label in (
            ("outcome_summary", gettext("outcome summary")),
            ("deliverables", gettext("deliverables")),
            ("impact_summary", gettext("impact summary")),
            ("lessons_learned", gettext("lessons learned")),
        )
        if not values[field]
    ]
    if missing:
        raise CompletionSummaryError(
            gettext("completion requires: %(fields)s") % {"fields": ", ".join(missing)}
        )
    values["deliverables"] = _normalize_deliverables(deliverables)
    return values


def validate_completion_summary(project: Project) -> None:
    """GOV-009/A14: require complete structured closure evidence before completion."""
    missing = []
    for field, label in (
        ("outcome_summary", gettext("outcome summary")),
        ("deliverables", gettext("deliverables")),
        ("impact_summary", gettext("impact summary")),
        ("lessons_learned", gettext("lessons learned")),
    ):
        if not getattr(project, field):
            missing.append(label)
    if missing:
        raise CompletionSummaryError(
            gettext("completion requires: %(fields)s") % {"fields": ", ".join(missing)}
        )
    _validated_completion_summary(
        outcome_summary=project.outcome_summary,
        deliverables=project.deliverables,
        impact_summary=project.impact_summary,
        lessons_learned=project.lessons_learned,
    )


def save_completion_summary(
    actor,
    project: Project,
    *,
    outcome_summary,
    deliverables,
    impact_summary,
    lessons_learned,
) -> Project:
    """GOV-005/GOV-009: save audited closure evidence before completion."""
    _require_owner_or_super_admin(actor, project, action="project.completion_summary.update")
    if project.project_type != ProjectType.GOVERNMENT:
        raise CompletionSummaryError(gettext("completion summaries apply to government projects"))
    if project.status not in {ProjectStatus.OPEN_FOR_CONTRIBUTION, ProjectStatus.PAUSED}:
        raise CompletionSummaryError(
            gettext("completion summary can be edited only while a project is open or paused")
        )
    values = _validated_completion_summary(
        outcome_summary=outcome_summary,
        deliverables=deliverables,
        impact_summary=impact_summary,
        lessons_learned=lessons_learned,
    )
    before = {
        field: getattr(project, field)
        for field in ("outcome_summary", "deliverables", "impact_summary", "lessons_learned")
    }
    with transaction.atomic():
        for field, value in values.items():
            setattr(project, field, value)
        project.save(update_fields=list(values))
        _audit_transition(
            actor,
            project,
            "completion_summary_updated",
            before,
            values,
        )
    return project


def complete(actor, project: Project) -> Project:
    """GOV-004/GOV-009: completion publishes outcome state and stops new work."""
    _require_owner_or_super_admin(actor, project, action="project.complete")
    if project.project_type == ProjectType.GOVERNMENT:
        validate_completion_summary(project)
    return _perform_transition(project, ProjectStatus.COMPLETED, actor=actor, action="completed")


def cancel(actor, project: Project, *, reason: str = "") -> Project:
    """GOV-004: cancellation records its reason; no new work is accepted."""
    _require_owner_or_super_admin(actor, project, action="project.cancel")
    if reason:
        project.outcome_summary = reason
        project.save(update_fields=["outcome_summary"])
    return _perform_transition(project, ProjectStatus.CANCELLED, actor=actor, action="cancelled")


def archive(actor, project: Project, *, reason: str = "") -> Project:
    """GOV-004: archival retains a read-only historical record."""
    _require_owner_or_super_admin(actor, project, action="project.archive")
    if reason:
        project.archive_reason = reason
        project.save(update_fields=["archive_reason"])
    return _perform_transition(project, ProjectStatus.ARCHIVED, actor=actor, action="archived")


def restore(super_admin, project: Project, *, to_status: str | None = None) -> Project:
    """GOV-004: only a Super Admin restores an archived project to its prior state."""
    _require_super_admin(super_admin, action="project.restore", obj=project)
    if project.status != ProjectStatus.ARCHIVED:
        raise ProjectLifecycleError("restore applies only to archived projects")
    target = to_status or _prior_status_from_audit(project)
    if target not in RESTORE_TARGETS:
        raise ProjectLifecycleError(f"restore target '{target}' is not a valid pre-archive state")
    _review_row(
        project,
        super_admin,
        "restored",
        comment="",
        from_status=ProjectStatus.ARCHIVED,
        to_status=target,
    )
    project.archived_at = None
    project.save(update_fields=["archived_at"])
    return _perform_transition(
        project,
        target,
        actor=super_admin,
        action="restored",
        allowed_override=True,
    )


def _prior_status_from_audit(project: Project) -> str | None:
    content_type = ContentType.objects.get_for_model(Project)
    archived_event = (
        AuditEvent.objects.filter(
            action="project.archived",
            content_type=content_type,
            object_id=str(project.pk),
        )
        .order_by("-created_at")
        .first()
    )
    if archived_event is None:
        return None
    return (archived_event.before or {}).get("status")


def reopen(super_admin, project: Project) -> Project:
    """GOV-004: a completed or cancelled project reopens only by approval."""
    _require_super_admin(super_admin, action="project.reopen", obj=project)
    if project.status not in {ProjectStatus.COMPLETED, ProjectStatus.CANCELLED}:
        raise ProjectLifecycleError(
            f"transition from '{project.status}' to '{ProjectStatus.OPEN_FOR_CONTRIBUTION}' "
            f"is not allowed by the SRS 6.1 lifecycle"
        )
    violations = check_publish_readiness(project)
    if violations:
        raise PublishReadinessError(violations)
    return _perform_transition(
        project,
        ProjectStatus.OPEN_FOR_CONTRIBUTION,
        actor=super_admin,
        action="reopened",
    )


def current_community_terms_version() -> str:
    """PPR-006: the version of the community terms currently in force."""
    return COMMUNITY_TERMS_VERSION


def has_accepted_community_terms(user, *, version: str = COMMUNITY_TERMS_VERSION) -> bool:
    """PPR-006: whether the member accepted the given community-terms version."""
    if not (user and getattr(user, "is_authenticated", False) and getattr(user, "pk", None)):
        return False
    return CommunityTermsAcceptance.objects.filter(user=user, version=version).exists()


def accept_community_terms(
    user, *, version: str = COMMUNITY_TERMS_VERSION
) -> CommunityTermsAcceptance:
    """PPR-006: record a member's acceptance of the current community terms, audited once."""
    if not (
        user and getattr(user, "is_authenticated", False) and getattr(user, "is_active", False)
    ):
        raise ProjectAuthorizationError("an active member account is required to accept terms")
    acceptance, created = CommunityTermsAcceptance.objects.get_or_create(user=user, version=version)
    if created:
        record_audit(
            actor=user,
            action="project.community_terms_accepted",
            obj=acceptance,
            after={"version": version},
        )
    return acceptance


def open_personal_listing(owner, project: Project) -> Project:
    """PPR-001/PPR-006: a member publishes their own community listing after accepting terms."""
    _require_publisher(owner, project, action="project.open_personal")
    if project.project_type != ProjectType.PERSONAL:
        raise ProjectLifecycleError("government projects must go through review (GOV-004)")
    if not has_accepted_community_terms(owner):
        raise ProjectLifecycleError(
            "accepting the current community terms is required before publishing (PPR-006)"
        )
    if not project.summary_en.strip():
        raise ProjectLifecycleError("a personal listing requires a summary")
    return _perform_transition(
        project,
        ProjectStatus.OPEN_FOR_CONTRIBUTION,
        actor=owner,
        action="personal_listing_opened",
    )


def unpublish_personal_listing(owner, project: Project) -> Project:
    """PPR-001: return an open personal listing to its non-public draft state."""
    _require_publisher(owner, project, action="project.unpublish_personal")
    if project.project_type != ProjectType.PERSONAL:
        raise ProjectLifecycleError("only personal projects may be unpublished")
    return _perform_transition(
        project,
        ProjectStatus.DRAFT,
        actor=owner,
        action="personal_listing_unpublished",
    )


# ---------------------------------------------------------------------------
# GitHub ownership verification (PPR-004)


def parse_github_repo_slug(url: str) -> str | None:
    """PPR-004: resolve a GitHub repository URL to its owner/repo slug (None otherwise)."""
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return None
    if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
        return None
    segments = [segment for segment in parsed.path.split("/") if segment]
    if len(segments) < 2:
        return None
    return f"{segments[0]}/{segments[1].removesuffix('.git')}"


def _fetch_github_repo_via_api(repo_slug: str) -> dict:
    """PPR-004: public-API lookup; an optional configured token avoids rate limits."""
    token = str(getattr(settings, "GITHUB_API_TOKEN", "") or "")
    url = f"https://api.github.com/repos/{quote(repo_slug, safe='/')}"
    if urlparse(url).scheme != "https" or urlparse(url).hostname != "api.github.com":
        raise GitHubVerificationError("refusing to open a non-HTTPS GitHub API URL")
    request = UrlRequest(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "devnepal"},
    )
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urlopen(request, timeout=10) as response:  # noqa: S310
        if response.status != 200:
            raise GitHubVerificationError(f"unexpected GitHub API status {response.status}")
        return json.load(response)


def _record_github_verify_failure(owner, project: Project, repo_slug: str, note: str) -> None:
    record_audit(
        actor=owner,
        action="project.github_verify_failed",
        obj=project,
        after={
            "repository": repo_slug,
            "ownership_verification": OwnershipVerificationStatus.UNVERIFIED,
            "note": note,
        },
        result="failure",
    )


def request_github_ownership_verification(owner, project: Project, *, fetcher=None) -> str:
    """PPR-004: verify the listing owner owns the connected GitHub repository.

    The public API owner login must match the owner's connected GitHub account.
    Any lookup failure (missing connection, API outage, token-gated rate
    limits) degrades gracefully to UNVERIFIED with an audited note.
    """
    _require_publisher(owner, project, action="project.github_verify")
    if project.project_type != ProjectType.PERSONAL:
        raise ProjectLifecycleError(
            "ownership verification applies to personal listings only (PPR-004)"
        )
    repo_slug = parse_github_repo_slug(project.repository_url)
    if repo_slug is None:
        raise ProjectLifecycleError(
            "a GitHub repository URL is required for ownership verification (PPR-004)"
        )

    connection = GithubConnection.objects.filter(user=owner, revoked_at__isnull=True).first()
    if connection is None:
        _record_github_verify_failure(owner, project, repo_slug, "no connected GitHub account")
        return OwnershipVerificationStatus.UNVERIFIED

    fetch = fetcher or _fetch_github_repo_via_api
    try:
        payload = fetch(repo_slug)
    except Exception:
        logger.exception("github ownership lookup failed; project=%s", project.pk)
        _record_github_verify_failure(
            owner, project, repo_slug, "GitHub API unavailable; verification not completed"
        )
        return OwnershipVerificationStatus.UNVERIFIED

    remote_login = str((payload or {}).get("owner", {}).get("login", "")).strip()
    if remote_login.lower() != connection.login.strip().lower():
        _record_github_verify_failure(
            owner,
            project,
            repo_slug,
            "repository owner does not match the connected GitHub account",
        )
        return OwnershipVerificationStatus.UNVERIFIED

    before = project.ownership_verification
    project.ownership_verification = OwnershipVerificationStatus.VERIFIED_GITHUB
    project.save(update_fields=["ownership_verification"])
    record_audit(
        actor=owner,
        action="project.github_verified",
        obj=project,
        before={"ownership_verification": before},
        after={
            "ownership_verification": OwnershipVerificationStatus.VERIFIED_GITHUB,
            "repository": repo_slug,
            "login": connection.login,
        },
    )
    return project.ownership_verification


# ---------------------------------------------------------------------------
# Edits and the material-edit rule (GOV-006, D2)


NON_EDITABLE_FIELDS = {
    "id",
    "project_type",
    "ministry",
    "owner",
    "status",
    "status_changed_at",
    "published_at",
    "current_version",
    "archived_at",
    "created_at",
    "updated_at",
}


def _editable_field_names() -> set[str]:
    names = set()
    for field in Project._meta.concrete_fields:
        if field.name in NON_EDITABLE_FIELDS:
            continue
        names.add(field.name)
        names.add(field.attname)
    return names


def apply_edit(publisher, project: Project, **changes) -> Project:
    """GOV-006/D2: apply a publisher edit; material edits on public projects re-enter review."""
    _require_publisher(publisher, project, action="project.edit")
    if project.status not in EDITABLE_STATES:
        raise MaterialEditError(
            f"project in status '{project.status}' cannot be edited; "
            f"only drafts, changes-requested, open, and paused projects accept edits"
        )

    known = _editable_field_names()
    unknown = sorted(set(changes) - known)
    if unknown:
        raise MaterialEditError(f"unknown or read-only fields: {', '.join(unknown)}")

    changed_material: list[str] = []
    update_field_names: set[str] = set()
    for field_name, new_value in changes.items():
        field = Project._meta.get_field(field_name)
        old_value = getattr(project, field.attname)
        if old_value != new_value and (
            field_name in MATERIAL_EDIT_FIELDS or field.attname in MATERIAL_EDIT_FIELDS
        ):
            changed_material.append(field_name)
        setattr(project, field_name, new_value)
        update_field_names.add(field.name)

    if not update_field_names:
        return project
    project.save(update_fields=sorted(update_field_names))

    if changed_material and project.status in MATERIAL_EDIT_REVIEW_STATES:
        version = create_version(project, submitted_by=publisher)
        _audit_transition(
            publisher,
            project,
            "material_edit",
            {"status": project.status, "changed": changed_material},
            {"status": ProjectStatus.IN_REVIEW, "changed": changed_material},
        )
        project.status = ProjectStatus.IN_REVIEW
        project.status_changed_at = timezone.now()
        project.save(update_fields=["status", "status_changed_at"])
        _schedule_review_queue_notifications(project, version)
    return project


def assign_maintainer(
    actor, project: Project, *, user, role: str, can_review_merge: bool
) -> ProjectMaintainer:
    """GOV-001/GOV-002: assign a named maintainer within the owning ministry's project."""
    _require_publisher(actor, project, action="project.maintainer.assign")
    if project.status == ProjectStatus.ARCHIVED:
        raise ProjectLifecycleError("archived projects are read-only")
    maintainer, created = ProjectMaintainer.objects.update_or_create(
        project=project,
        user=user,
        defaults={"role": role, "can_review_merge": can_review_merge},
    )
    record_audit(
        actor=actor,
        action="project.maintainer_assigned",
        obj=project,
        after={
            "maintainer_id": user.pk,
            "role": role,
            "can_review_merge": can_review_merge,
            "created": created,
        },
    )
    return maintainer


def _screening_question_or_error(project: Project, question_id) -> ProjectScreeningQuestion:
    try:
        question_pk = int(question_id)
    except (TypeError, ValueError) as exc:
        raise ProjectLifecycleError("a screening question id is required") from exc
    question = project.screening_questions.filter(pk=question_pk).first()
    if question is None:
        raise ProjectLifecycleError(
            f"screening question {question_id} is not configured for this project (DSC-006)"
        )
    return question


def add_screening_question(
    actor,
    project: Project,
    *,
    question: str,
    help_text: str = "",
    is_required: bool = True,
    sort_order: int = 0,
) -> ProjectScreeningQuestion:
    """DSC-006: an authorized publisher configures an application screening question."""
    _require_publisher(actor, project, action="project.screening_question.add")
    if project.status == ProjectStatus.ARCHIVED:
        raise ProjectLifecycleError("archived projects are read-only")
    screening = ProjectScreeningQuestion.objects.create(
        project=project,
        question=question,
        help_text=help_text,
        is_required=is_required,
        sort_order=sort_order,
    )
    record_audit(
        actor=actor,
        action="project.screening_question_added",
        obj=screening,
        after={
            "project_id": project.pk,
            "is_required": screening.is_required,
            "is_active": screening.is_active,
        },
    )
    return screening


def set_screening_question_active(
    actor, project: Project, question_id, *, is_active: bool
) -> ProjectScreeningQuestion:
    """DSC-006: retire or restore a screening question without losing its history."""
    _require_publisher(actor, project, action="project.screening_question.toggle")
    question = _screening_question_or_error(project, question_id)
    before = question.is_active
    question.is_active = is_active
    question.save(update_fields=["is_active"])
    record_audit(
        actor=actor,
        action="project.screening_question_toggled",
        obj=question,
        before={"is_active": before},
        after={"is_active": is_active},
    )
    return question


def remove_screening_question(actor, project: Project, question_id) -> None:
    """DSC-006: an authorized publisher deletes a misconfigured screening question."""
    _require_publisher(actor, project, action="project.screening_question.remove")
    question = _screening_question_or_error(project, question_id)
    removed = {"question": question.question, "is_active": question.is_active}
    question.delete()
    record_audit(
        actor=actor,
        action="project.screening_question_removed",
        obj=project,
        after=removed,
    )


def create_task(actor, project: Project, **fields) -> ProjectTask:
    """GOV-002/GOV-007: add an actionable contribution task to an authorized project."""
    _require_publisher(actor, project, action="project.task.create")
    if project.status == ProjectStatus.ARCHIVED:
        raise ProjectLifecycleError("archived projects are read-only")
    skills = fields.pop("skills", [])
    task = ProjectTask.objects.create(project=project, **fields)
    task.skills.set(skills)
    record_audit(
        actor=actor,
        action="project.task_created",
        obj=task,
        after={"project_id": project.pk, "status": task.status},
    )
    return task


def create_milestone(actor, project: Project, **fields) -> ProjectMilestone:
    """GOV-002/GOV-009: add a project milestone to an authorized project."""
    _require_publisher(actor, project, action="project.milestone.create")
    if project.status == ProjectStatus.ARCHIVED:
        raise ProjectLifecycleError("archived projects are read-only")
    milestone = ProjectMilestone.objects.create(project=project, **fields)
    record_audit(
        actor=actor,
        action="project.milestone_created",
        obj=milestone,
        after={"project_id": project.pk, "status": milestone.status},
    )
    return milestone


def complete_suitability(
    actor, project: Project, *, checklist: dict, notes: str
) -> ProjectSuitability:
    """BR-002: record the ministry's completed public-contribution suitability checklist."""
    _require_publisher(actor, project, action="project.suitability.complete")
    if project.status == ProjectStatus.ARCHIVED:
        raise ProjectLifecycleError("archived projects are read-only")
    suitability, _ = ProjectSuitability.objects.get_or_create(project=project)
    suitability.checklist = checklist
    suitability.notes = notes
    suitability.completed_by = actor
    suitability.completed_at = timezone.now()
    suitability.save(update_fields=["checklist", "notes", "completed_by", "completed_at"])
    record_audit(
        actor=actor,
        action="project.suitability_completed",
        obj=project,
        after={
            "checked_areas": sorted(area for area, value in checklist.items() if value["checked"])
        },
    )
    return suitability


def confirm_suitability(super_admin, project: Project) -> ProjectSuitability:
    """BR-002: Super Admin confirms a ministry-completed suitability checklist."""
    _require_super_admin(super_admin, action="project.suitability.confirm", obj=project)
    suitability = ProjectSuitability.objects.filter(
        project=project, completed_at__isnull=False
    ).first()
    if suitability is None:
        raise ProjectLifecycleError("the ministry must complete the suitability checklist first")
    if not all(
        suitability.checklist.get(area, {}).get("checked", False) for area in SUITABILITY_AREAS
    ):
        raise ProjectLifecycleError(
            "all suitability checklist areas must be confirmed before approval"
        )
    suitability.confirmed_by = super_admin
    suitability.confirmed_at = timezone.now()
    suitability.save(update_fields=["confirmed_by", "confirmed_at"])
    record_audit(
        actor=super_admin,
        action="project.suitability_confirmed",
        obj=project,
        after={"confirmed_by": super_admin.pk},
    )
    return suitability


# ---------------------------------------------------------------------------
# Updates and completion (GOV-009)


def _can_post_update(actor, project: Project) -> bool:
    if _is_super_admin(actor):
        require_privileged_mfa(
            actor, action="project.update", obj=project, error_type=ProjectAuthorizationError
        )
        return True
    if project.project_type == ProjectType.PERSONAL:
        return bool(actor and actor.is_active and project.owner_id == actor.pk)
    if is_publisher_active(actor, project.ministry):
        require_privileged_mfa(
            actor, action="project.update", obj=project, error_type=ProjectAuthorizationError
        )
        return True
    return project.maintainer_assignments.filter(user_id=actor.pk).exists() if actor else False


def post_update(
    actor, project: Project, *, title: str, body: str, kind: str = "progress", link: str = ""
) -> ProjectUpdate:
    """GOV-009: publishers and maintainers post progress, milestone, release, completion updates."""
    if not _can_post_update(actor, project):
        record_audit(actor=actor, action="project.update.denied", obj=project, result="failure")
        raise ProjectAuthorizationError(
            "only the owning publisher or a maintainer may post updates"
        )
    if project.status == ProjectStatus.ARCHIVED:
        raise ProjectLifecycleError("archived projects are read-only")
    update = ProjectUpdate.objects.create(
        project=project, title=title, body=body, kind=kind, link=link, created_by=actor
    )
    project.last_maintainer_activity_at = timezone.now()
    project.save(update_fields=["last_maintainer_activity_at"])
    return update


# ---------------------------------------------------------------------------
# Deadline expiry and maintainer SLA (GOV-010, GOV-012, D5)


def default_response_sla_days() -> int:
    return int(getattr(settings, "DEFAULT_RESPONSE_SLA_DAYS", 5))


def response_sla_days(project: Project) -> int:
    """DSC-009: the project's published first-response window in whole days."""
    return RESPONSE_SLA_DAYS.get(project.response_sla, default_response_sla_days())


def latest_public_update(project: Project):
    """DSC-009: the newest update, reusing the list prefetch when present."""
    updates = list(project.updates.all())
    if not updates:
        return None
    return max(updates, key=lambda update: update.created_at)


def response_overdue(project: Project, *, now: datetime | None = None) -> bool:
    """DSC-009: a live project waiting longer than its SLA since the latest update."""
    if project.status not in {ProjectStatus.OPEN_FOR_CONTRIBUTION, ProjectStatus.PAUSED}:
        return False
    update = latest_public_update(project)
    anchor = update.created_at if update is not None else project.published_at
    if anchor is None:
        return False
    moment = now or timezone.now()
    return moment - anchor > timedelta(days=response_sla_days(project))


def deadline_expired(project: Project, *, today: date | None = None) -> bool:
    """GOV-010: a passed deadline on a live project is expired, never auto-closed."""
    if project.deadline is None:
        return False
    if project.status not in {ProjectStatus.OPEN_FOR_CONTRIBUTION, ProjectStatus.PAUSED}:
        return False
    return project.deadline < (today or timezone.localdate())


def _flag_recorded_once(project: Project, action: str) -> bool:
    content_type = ContentType.objects.get_for_model(Project)
    return AuditEvent.objects.filter(
        action=action, content_type=content_type, object_id=str(project.pk)
    ).exists()


def flag_expired(project: Project, *, today: date | None = None) -> bool:
    """GOV-010: record the expiry flag; the owner must still act explicitly."""
    if not deadline_expired(project, today=today):
        return False
    if not _flag_recorded_once(project, "project.deadline_expired"):
        record_audit(
            actor=None,
            action="project.deadline_expired",
            obj=project,
            before=_status_payload(project),
            after=_status_payload(project, flag="deadline_expired"),
            source="system",
        )
    return True


def extend_deadline(actor, project: Project, new_deadline: date) -> Project:
    """GOV-010: the explicit owner action that clears an expired deadline."""
    _require_owner_or_super_admin(actor, project, action="project.extend_deadline")
    if new_deadline is None:
        raise ProjectLifecycleError("a new deadline date is required")
    if new_deadline <= timezone.localdate():
        raise ProjectLifecycleError("the new deadline must be in the future")
    before = project.deadline.isoformat() if project.deadline else None
    project.deadline = new_deadline
    project.save(update_fields=["deadline"])
    record_audit(
        actor=actor,
        action="project.deadline_extended",
        obj=project,
        before={"deadline": before},
        after={"deadline": new_deadline.isoformat()},
    )
    return project


def maintainer_response_stale(project: Project, *, now: datetime | None = None) -> bool:
    """GOV-012/D5: stale when no maintainer response for more than twice the SLA."""
    anchor = project.last_maintainer_activity_at or project.published_at
    if anchor is None:
        return False
    if project.status not in {ProjectStatus.OPEN_FOR_CONTRIBUTION, ProjectStatus.PAUSED}:
        return False
    threshold = timedelta(days=2 * default_response_sla_days())
    return (now or timezone.now()) - anchor > threshold


def flag_stale(project: Project, *, now: datetime | None = None) -> bool:
    """GOV-012: flag the project to the ministry and Super Admin (audit record)."""
    if not maintainer_response_stale(project, now=now):
        return False
    if not _flag_recorded_once(project, "project.maintainer_sla_flagged"):
        record_audit(
            actor=None,
            action="project.maintainer_sla_flagged",
            obj=project,
            before=_status_payload(project),
            after=_status_payload(project, flag="maintainer_sla_stale"),
            source="system",
        )
    return True


# ---------------------------------------------------------------------------
# Attachments (GOV-003, SEC-007, SEC-004)


def max_attachment_bytes() -> int:
    return int(getattr(settings, "MAX_ATTACHMENT_BYTES", 25 * 1024 * 1024))


CONTENT_SIGNATURES = {
    ".pdf": (b"%PDF-",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".zip": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
    ".docx": (b"PK\x03\x04",),
    ".pptx": (b"PK\x03\x04",),
    ".xlsx": (b"PK\x03\x04",),
}
EXECUTABLE_SIGNATURES = (b"MZ", b"\x7fELF", b"#!")


def _validate_attachment_content(file, suffix: str) -> None:
    position = file.tell() if hasattr(file, "tell") else None
    try:
        sample = file.read(16)
    finally:
        if position is not None and hasattr(file, "seek"):
            file.seek(position)

    if any(sample.startswith(signature) for signature in EXECUTABLE_SIGNATURES):
        raise AttachmentError("file content is executable or scriptable")

    expected = CONTENT_SIGNATURES.get(suffix)
    if expected and not any(sample.startswith(signature) for signature in expected):
        raise AttachmentError("file content does not match its declared type")


def add_attachment(
    actor,
    project: Project,
    *,
    kind: str,
    file,
    language: str = "en",
    classification: str = "public",
    accessibility_note: str = "",
) -> ProjectAttachment:
    """GOV-003/SEC-007: validated upload with versioned replacement per kind."""
    _require_owner_or_super_admin(actor, project, action="project.attachment.add")
    suffix = PurePosixPath(file.name).suffix.lower()
    if suffix in BLOCKED_ATTACHMENT_SUFFIXES:
        raise AttachmentError(f"files of type '{suffix}' are not accepted")
    _validate_attachment_content(file, suffix)
    if file.size is not None and file.size > max_attachment_bytes():
        raise AttachmentError("file exceeds the maximum attachment size")
    version = (
        ProjectAttachment.objects.filter(project=project, kind=kind)
        .order_by("-version")
        .values_list("version", flat=True)
        .first()
        or 0
    ) + 1
    return ProjectAttachment.objects.create(
        project=project,
        kind=kind,
        file=file,
        original_filename=file.name,
        content_type=getattr(file, "content_type", "") or "",
        size_bytes=file.size or 0,
        version=version,
        language=language,
        classification=classification,
        accessibility_note=accessibility_note,
        uploaded_by=actor,
    )


def record_scan_result(attachment: ProjectAttachment, scan_status: str) -> ProjectAttachment:
    """SEC-007/GOV-003: quarantined or failed files are purged and never served."""
    if scan_status in {ScanStatus.QUARANTINED, ScanStatus.FAILED}:
        attachment.scan = ScanStatus.QUARANTINED
        attachment.file.delete(save=False)
        attachment.file = None
        attachment.save(update_fields=["scan", "file"])
    else:
        attachment.scan = scan_status
        attachment.save(update_fields=["scan"])
    record_audit(
        actor=None,
        action="project.attachment_scanned",
        obj=attachment,
        before={"scan": ScanStatus.PENDING},
        after={"scan": attachment.scan},
        source="system",
    )
    return attachment


# ---------------------------------------------------------------------------
# Applications (DSC-005..DSC-008, BR-011)


def _require_active_member(member) -> None:
    if not (member and getattr(member, "is_active", False)):
        raise ApplicationError("an active member account is required")


def apply_to_project(
    member,
    project: Project,
    *,
    answers: list | None = None,
    kind: str = ParticipationKind.APPLICATION,
    motivation: str = "",
) -> Application:
    """DSC-005/DSC-006/BR-011: create an application or interest record on an open project."""
    _require_active_member(member)
    if project.status in APPLICATION_BLOCKED_STATES:
        raise ApplicationClosedError(
            f"project in status '{project.status}' does not accept new applications (BR-011)"
        )
    if project.status != ProjectStatus.OPEN_FOR_CONTRIBUTION:
        raise ApplicationClosedError(
            f"project in status '{project.status}' is not open for contribution"
        )
    if kind in {ParticipationKind.APPLICATION, ParticipationKind.ASSIGNMENT} and (
        project.contribution_mode == "open_direct"
    ):
        raise ApplicationError(
            "project accepts direct contributions only; follow the published instructions (DSC-005)"
        )
    if Application.objects.filter(project=project, applicant=member, kind=kind).exists():
        raise ApplicationError("an application of this kind already exists for this project")

    screening = _validated_screening_answers(project, answers or [])

    with transaction.atomic():
        application = Application.objects.create(
            project=project,
            applicant=member,
            kind=kind,
            motivation=motivation,
            screening_answers=screening,
        )
        event = ApplicationEvent.objects.create(
            application=application,
            actor=member,
            event=ApplicationEventType.SUBMITTED,
            comment=motivation,
            from_status="",
            to_status=ApplicationStatus.SUBMITTED,
        )
        if project.ministry_id is not None:
            try:
                record_event(
                    EventName.PROJECT_APPLIED,
                    project=project,
                    source_ref=f"application:{application.pk}",
                )
            except AnalyticsError as error:
                logger.exception(
                    "Application analytics recording failed; application_id=%s", application.pk
                )
                raise ApplicationAnalyticsError(
                    "application analytics event could not be recorded"
                ) from error
        _schedule_application_submission_notifications(application, event)
    return application


def _validated_screening_answers(project: Project, answers: list) -> list[dict]:
    questions = {
        question.pk: question for question in project.screening_questions.filter(is_active=True)
    }
    provided = {}
    for entry in answers:
        try:
            question_id = int(entry["question_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ApplicationError("each answer must reference a screening question") from exc
        if question_id not in questions:
            raise ApplicationError(
                f"screening question {question_id} is not configured for this project (DSC-006)"
            )
        provided[question_id] = str(entry.get("answer", "")).strip()

    missing = [
        question.question
        for question in questions.values()
        if question.is_required and not provided.get(question.pk, "")
    ]
    if missing:
        raise ApplicationError("required screening questions unanswered: " + "; ".join(missing))

    return [
        {
            "question_id": question.pk,
            "question": question.question,
            "answer": provided.get(question.pk, ""),
        }
        for question in sorted(questions.values(), key=lambda q: q.sort_order)
    ]


def _require_application_decider(actor, application: Application) -> None:
    if _is_super_admin(actor):
        require_privileged_mfa(
            actor,
            action="application.decide",
            obj=application,
            error_type=ApplicationAuthorizationError,
        )
        return
    project = application.project
    if project.project_type == ProjectType.PERSONAL:
        if actor and actor.is_active and project.owner_id == actor.pk:
            return
    elif is_publisher_active(actor, project.ministry):
        require_privileged_mfa(
            actor,
            action="application.decide",
            obj=application,
            error_type=ApplicationAuthorizationError,
        )
        return
    record_audit(actor=actor, action="application.decide.denied", obj=application, result="failure")
    raise ApplicationAuthorizationError(
        "only a publisher of the owning ministry or a Super Admin may decide applications"
    )


def decide_application(
    decider, application: Application, decision: str, *, note: str = ""
) -> Application:
    """DSC-007: accept/waitlist/decline/request-info with auditable status and template note."""
    _require_application_decider(decider, application)
    from_status = application.status
    allowed = APPLICATION_DECISION_TRANSITIONS.get(from_status, set())
    if decision not in allowed:
        raise ApplicationDecisionError(
            f"application decision '{decision}' is not available from status '{from_status}'"
        )
    with transaction.atomic():
        application.status = decision
        application.decided_by = decider
        application.decided_at = timezone.now()
        application.decision_note = note
        application.save(
            update_fields=["status", "decided_by", "decided_at", "decision_note", "updated_at"]
        )
        event = ApplicationEvent.objects.create(
            application=application,
            actor=decider,
            event=(
                ApplicationEventType.INFO_REQUESTED
                if decision == ApplicationStatus.INFO_REQUESTED
                else ApplicationEventType.STATUS_CHANGED
            ),
            comment=note,
            from_status=from_status,
            to_status=decision,
        )
        record_audit(
            actor=decider,
            action="application.decided",
            obj=application,
            before={"status": from_status},
            after={"status": decision},
        )
    _schedule_application_decision_notification(application, event)
    return application


def provide_info(applicant, application: Application, text: str) -> ApplicationEvent:
    """DSC-007/DSC-008: the applicant answers an information request on the timeline."""
    if application.applicant_id != getattr(applicant, "pk", None):
        raise ApplicationAuthorizationError("only the applicant may provide information")
    if application.status != ApplicationStatus.INFO_REQUESTED:
        raise ApplicationDecisionError(
            f"information can only be provided while status is 'info_requested', "
            f"not '{application.status}'"
        )
    if not (text or "").strip():
        raise ApplicationDecisionError("provided information must not be empty")
    return ApplicationEvent.objects.create(
        application=application,
        actor=applicant,
        event=ApplicationEventType.INFO_PROVIDED,
        comment=text,
        from_status=application.status,
        to_status=application.status,
    )


def withdraw_application(applicant, application: Application) -> Application:
    """DSC-007: the applicant withdraws from any non-terminal pending status."""
    if application.applicant_id != getattr(applicant, "pk", None):
        raise ApplicationAuthorizationError("only the applicant may withdraw")
    if application.status not in {
        ApplicationStatus.SUBMITTED,
        ApplicationStatus.INFO_REQUESTED,
        ApplicationStatus.WAITLISTED,
    }:
        raise ApplicationDecisionError(
            f"withdrawal is not available from status '{application.status}'"
        )
    from_status = application.status
    application.status = ApplicationStatus.WITHDRAWN
    application.save(update_fields=["status", "updated_at"])
    ApplicationEvent.objects.create(
        application=application,
        actor=applicant,
        event=ApplicationEventType.WITHDRAWN,
        from_status=from_status,
        to_status=ApplicationStatus.WITHDRAWN,
    )
    return application


def can_view_timeline(user, application: Application) -> bool:
    """DSC-008: the member and authorized ministry users see the timeline."""
    if user is None or not getattr(user, "is_active", False):
        return False
    if application.applicant_id == user.pk:
        return True
    if _is_super_admin(user):
        return True
    project = application.project
    if project.project_type == ProjectType.PERSONAL:
        return project.owner_id == user.pk
    return is_publisher_active(user, project.ministry)


# ---------------------------------------------------------------------------
# Explainable recommendations (DSC-010)

SKILL_MATCH_WEIGHT = 3
CONTRIBUTION_TYPE_MATCH_WEIGHT = 2
EXPERIENCE_MATCH_WEIGHT = 2
SAVED_PROJECT_MATCH_WEIGHT = 1


@dataclass(frozen=True)
class ProjectRecommendation:
    """DSC-010: an explainable recommendation; cited reasons only, never a raw score."""

    project: Project
    reasons: tuple[str, ...]


def _member_skill_reasons(user) -> list[tuple[str, str]]:
    rows = MemberSkill.objects.filter(user=user).select_related("skill").order_by("skill__name")
    return [
        (
            member_skill.skill.name,
            gettext("Matches your %s skill") % member_skill.skill.name,
        )
        for member_skill in rows
    ]


def _member_contribution_type_reasons(user) -> dict[int, str]:
    rows = (
        ContributionRecord.objects.filter(
            contributor=user,
            status=VerificationStatus.ACCEPTED,
            contribution_type__is_active=True,
        )
        .values_list("contribution_type_id", "contribution_type__label")
        .distinct()
        .order_by("contribution_type__label")
    )
    return {
        type_id: gettext("Matches your %s contribution history") % label for type_id, label in rows
    }


def _saved_ministry_ids(user) -> set[int]:
    return set(
        ProjectBookmark.objects.filter(user=user, project__ministry__isnull=False).values_list(
            "project__ministry_id", flat=True
        )
    )


def recommended_projects(user, limit: int = 6) -> list[ProjectRecommendation]:
    """DSC-010: rank open projects by explicit profile attributes, citing the reasons.

    Ranking uses only explicit member profile data — shared skills, verified
    contribution types, ministries of saved projects, and the declared
    experience band matched against a project's demand. Candidates are public
    open projects; the member's own projects and already-applied projects are
    excluded (BR-004). Ordering is deterministic (score descending, then
    title). Reasons are returned instead of scores; nothing opaque leaves here.
    """
    if limit <= 0:
        return []
    if not (
        user
        and getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
        and getattr(user, "pk", None)
    ):
        return []

    skill_reasons = _member_skill_reasons(user)
    contribution_reasons = _member_contribution_type_reasons(user)
    saved_ministries = _saved_ministry_ids(user)
    experience_band = (
        MemberProfile.objects.filter(user=user).values_list("experience_band", flat=True).first()
        or ""
    )

    candidates = (
        Project.objects.filter(status=ProjectStatus.OPEN_FOR_CONTRIBUTION)
        .exclude(owner=user)
        .exclude(applications__applicant=user)
        .exclude(bookmarks__user=user)
        .select_related("ministry")
        .prefetch_related("skills", "contribution_types")
        .distinct()
    )

    scored: list[tuple[int, str, ProjectRecommendation]] = []
    for project in candidates:
        reasons: list[str] = []
        score = 0

        project_skills = {project_skill.name for project_skill in project.skills.all()}
        for skill_name, reason in skill_reasons:
            if skill_name in project_skills:
                score += SKILL_MATCH_WEIGHT
                reasons.append(reason)

        project_types = {term.pk for term in project.contribution_types.all()}
        for type_id, reason in contribution_reasons.items():
            if type_id in project_types:
                score += CONTRIBUTION_TYPE_MATCH_WEIGHT
                reasons.append(reason)

        if experience_band and experience_band in {
            project.experience_band,
            project.difficulty,
        }:
            score += EXPERIENCE_MATCH_WEIGHT
            reasons.append(gettext("Matches your %s experience level") % experience_band)

        if project.ministry_id and project.ministry_id in saved_ministries:
            score += SAVED_PROJECT_MATCH_WEIGHT
            reasons.append(gettext("Similar to a project you saved"))

        if reasons:
            scored.append((score, project.title_en, ProjectRecommendation(project, tuple(reasons))))

    scored.sort(key=lambda entry: (-entry[0], entry[1]))
    return [entry[2] for entry in scored[:limit]]
