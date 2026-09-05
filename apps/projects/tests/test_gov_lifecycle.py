import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.audit.models import AuditEvent
from apps.projects.enums import ProjectStatus
from apps.projects.services import (
    ProjectAuthorizationError,
    ProjectLifecycleError,
    PublishReadinessError,
    add_attachment,
    approve,
    archive,
    cancel,
    complete,
    drafts_for_publisher,
    extend_deadline,
    open_personal_listing,
    pause,
    publish,
    publish_due_scheduled,
    reject_submission,
    reopen,
    request_changes,
    restore,
    resubmit,
    resume,
    revoke_approval,
    submit_for_review,
)
from apps.projects.tests.factories import (
    MinistryOrganizationFactory,
    PersonalProjectFactory,
    ProjectFactory,
    SuperAdminFactory,
    UserFactory,
    make_publishable,
)

pytestmark = [pytest.mark.django_db]

REACHABLE = {
    ProjectStatus.DRAFT: [],
    ProjectStatus.IN_REVIEW: [ProjectStatus.IN_REVIEW],
    ProjectStatus.CHANGES_REQUESTED: [ProjectStatus.IN_REVIEW, ProjectStatus.CHANGES_REQUESTED],
    ProjectStatus.APPROVED: [ProjectStatus.IN_REVIEW, ProjectStatus.APPROVED],
    ProjectStatus.OPEN_FOR_CONTRIBUTION: [
        ProjectStatus.IN_REVIEW,
        ProjectStatus.APPROVED,
        ProjectStatus.OPEN_FOR_CONTRIBUTION,
    ],
    ProjectStatus.PAUSED: [
        ProjectStatus.IN_REVIEW,
        ProjectStatus.APPROVED,
        ProjectStatus.OPEN_FOR_CONTRIBUTION,
        ProjectStatus.PAUSED,
    ],
    ProjectStatus.COMPLETED: [
        ProjectStatus.IN_REVIEW,
        ProjectStatus.APPROVED,
        ProjectStatus.OPEN_FOR_CONTRIBUTION,
        ProjectStatus.COMPLETED,
    ],
    ProjectStatus.CANCELLED: [
        ProjectStatus.IN_REVIEW,
        ProjectStatus.APPROVED,
        ProjectStatus.OPEN_FOR_CONTRIBUTION,
        ProjectStatus.CANCELLED,
    ],
    ProjectStatus.ARCHIVED: [
        ProjectStatus.IN_REVIEW,
        ProjectStatus.APPROVED,
        ProjectStatus.OPEN_FOR_CONTRIBUTION,
        ProjectStatus.ARCHIVED,
    ],
}


def walk_to(project, statuses, publisher, super_admin):
    for status in statuses:
        act = {
            ProjectStatus.IN_REVIEW: lambda: submit_for_review(publisher, project),
            ProjectStatus.CHANGES_REQUESTED: lambda: request_changes(
                super_admin, project, reason="Rework the summary"
            ),
            ProjectStatus.APPROVED: lambda: approve(super_admin, project),
            ProjectStatus.OPEN_FOR_CONTRIBUTION: lambda: publish(super_admin, project),
            ProjectStatus.PAUSED: lambda: pause(publisher, project),
            ProjectStatus.COMPLETED: lambda: complete(publisher, project),
            ProjectStatus.CANCELLED: lambda: cancel(publisher, project),
            ProjectStatus.ARCHIVED: lambda: archive(publisher, project, reason="Retention elapsed"),
        }[status]
        act()


@pytest.mark.integration
@pytest.mark.parametrize(
    ("from_status", "to_status", "actor_kind"),
    [
        (ProjectStatus.DRAFT, ProjectStatus.IN_REVIEW, "publisher"),
        (ProjectStatus.IN_REVIEW, ProjectStatus.CHANGES_REQUESTED, "super_admin"),
        (ProjectStatus.IN_REVIEW, ProjectStatus.APPROVED, "super_admin"),
        (ProjectStatus.IN_REVIEW, ProjectStatus.DRAFT, "super_admin"),
        (ProjectStatus.CHANGES_REQUESTED, ProjectStatus.IN_REVIEW, "publisher"),
        (ProjectStatus.APPROVED, ProjectStatus.OPEN_FOR_CONTRIBUTION, "super_admin"),
        (ProjectStatus.APPROVED, ProjectStatus.CHANGES_REQUESTED, "super_admin"),
        (ProjectStatus.OPEN_FOR_CONTRIBUTION, ProjectStatus.PAUSED, "publisher"),
        (ProjectStatus.OPEN_FOR_CONTRIBUTION, ProjectStatus.COMPLETED, "publisher"),
        (ProjectStatus.OPEN_FOR_CONTRIBUTION, ProjectStatus.CANCELLED, "publisher"),
        (ProjectStatus.OPEN_FOR_CONTRIBUTION, ProjectStatus.ARCHIVED, "publisher"),
        (ProjectStatus.PAUSED, ProjectStatus.OPEN_FOR_CONTRIBUTION, "publisher"),
        (ProjectStatus.PAUSED, ProjectStatus.COMPLETED, "publisher"),
        (ProjectStatus.PAUSED, ProjectStatus.CANCELLED, "publisher"),
        (ProjectStatus.PAUSED, ProjectStatus.ARCHIVED, "publisher"),
        (ProjectStatus.COMPLETED, ProjectStatus.ARCHIVED, "publisher"),
        (ProjectStatus.CANCELLED, ProjectStatus.ARCHIVED, "publisher"),
        (ProjectStatus.COMPLETED, ProjectStatus.OPEN_FOR_CONTRIBUTION, "super_admin"),
        (ProjectStatus.CANCELLED, ProjectStatus.OPEN_FOR_CONTRIBUTION, "super_admin"),
    ],
)
def test_exactly_the_legal_lifecycle_transitions_succeed(from_status, to_status, actor_kind):
    """GOV-004-U1: exactly the SRS 6.1 table transitions succeed, each audited with before/after."""
    project = make_publishable()
    publisher = project.owner
    super_admin = SuperAdminFactory()
    walk_to(project, REACHABLE[from_status], publisher, super_admin)
    project.refresh_from_db()
    assert project.status == from_status

    actor = super_admin if actor_kind == "super_admin" else publisher

    def perform():
        if to_status == ProjectStatus.IN_REVIEW:
            submit_for_review(publisher, project)
        elif to_status == ProjectStatus.CHANGES_REQUESTED:
            if from_status == ProjectStatus.APPROVED:
                revoke_approval(super_admin, project, reason="Approval withdrawn")
            else:
                request_changes(super_admin, project, reason="Rework")
        elif to_status == ProjectStatus.APPROVED:
            approve(super_admin, project)
        elif to_status == ProjectStatus.DRAFT:
            reject_submission(super_admin, project, reason="Incomplete")
        elif to_status == ProjectStatus.OPEN_FOR_CONTRIBUTION:
            if from_status == ProjectStatus.APPROVED:
                publish(super_admin, project)
            elif from_status == ProjectStatus.PAUSED:
                resume(actor, project)
            else:
                reopen(super_admin, project)
        elif to_status == ProjectStatus.PAUSED:
            pause(actor, project)
        elif to_status == ProjectStatus.COMPLETED:
            complete(actor, project)
        elif to_status == ProjectStatus.CANCELLED:
            cancel(actor, project)
        elif to_status == ProjectStatus.ARCHIVED:
            archive(actor, project, reason="Retention elapsed")

    perform()

    project.refresh_from_db()
    assert project.status == to_status
    assert AuditEvent.objects.filter(
        object_id=str(project.pk),
        action__startswith="project.",
        before__status=from_status,
        after__status=to_status,
    ).exists()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("from_status", "attempt"),
    [
        (ProjectStatus.DRAFT, "approve"),
        (ProjectStatus.DRAFT, "publish"),
        (ProjectStatus.DRAFT, "pause"),
        (ProjectStatus.DRAFT, "request_changes"),
        (ProjectStatus.IN_REVIEW, "publish"),
        (ProjectStatus.IN_REVIEW, "pause"),
        (ProjectStatus.IN_REVIEW, "resubmit"),
        (ProjectStatus.CHANGES_REQUESTED, "approve"),
        (ProjectStatus.CHANGES_REQUESTED, "publish"),
        (ProjectStatus.APPROVED, "pause"),
        (ProjectStatus.APPROVED, "submit"),
        (ProjectStatus.APPROVED, "resubmit"),
        (ProjectStatus.OPEN_FOR_CONTRIBUTION, "approve"),
        (ProjectStatus.OPEN_FOR_CONTRIBUTION, "submit"),
        (ProjectStatus.OPEN_FOR_CONTRIBUTION, "resubmit"),
        (ProjectStatus.OPEN_FOR_CONTRIBUTION, "resume"),
        (ProjectStatus.PAUSED, "approve"),
        (ProjectStatus.PAUSED, "publish"),
        (ProjectStatus.COMPLETED, "pause"),
        (ProjectStatus.COMPLETED, "resume"),
        (ProjectStatus.CANCELLED, "pause"),
        (ProjectStatus.ARCHIVED, "approve"),
        (ProjectStatus.ARCHIVED, "pause"),
        (ProjectStatus.ARCHIVED, "resume"),
    ],
)
def test_illegal_transition_raises_typed_lifecycle_error(from_status, attempt):
    """GOV-004-U2: an illegal transition raises ProjectLifecycleError naming both states."""
    project = make_publishable()
    publisher = project.owner
    super_admin = SuperAdminFactory()
    walk_to(project, REACHABLE[from_status], publisher, super_admin)
    project.refresh_from_db()

    attempts = {
        "approve": lambda: approve(super_admin, project),
        "publish": lambda: publish(super_admin, project),
        "pause": lambda: pause(publisher, project),
        "request_changes": lambda: request_changes(super_admin, project, reason="x"),
        "resubmit": lambda: resubmit(publisher, project),
        "submit": lambda: submit_for_review(publisher, project),
        "resume": lambda: resume(publisher, project),
    }
    with pytest.raises((ProjectLifecycleError, PublishReadinessError)) as excinfo:
        attempts[attempt]()
    message = str(excinfo.value)
    assert project.status in message or from_status in message
    project.refresh_from_db()
    assert project.status == from_status


@pytest.mark.integration
def test_publisher_scoped_drafts_and_foreign_ministry_denied():
    """GOV-001: publishers see and act only inside their assigned ministries."""
    home = MinistryOrganizationFactory()
    other = MinistryOrganizationFactory()
    publisher = UserFactory()
    from apps.ministries.tests.factories import MinistryPublisherFactory

    MinistryPublisherFactory(user=publisher, ministry=home)
    own_draft = ProjectFactory(ministry=home, owner=publisher)
    foreign_draft = ProjectFactory(ministry=other)

    assert list(drafts_for_publisher(publisher)) == [own_draft]

    with pytest.raises(ProjectAuthorizationError):
        submit_for_review(publisher, foreign_draft)
    foreign_draft.refresh_from_db()
    assert foreign_draft.status == ProjectStatus.DRAFT
    assert AuditEvent.objects.filter(
        action="project.submit.denied", object_id=str(foreign_draft.pk), result="failure"
    ).exists()


@pytest.mark.integration
def test_submit_requires_bilingual_title_and_summary():
    """GOV-002: government submission requires English and Nepali title and summary (14.3)."""
    project = make_publishable(summary_ne="")
    publisher = project.owner
    with pytest.raises(ProjectLifecycleError) as excinfo:
        submit_for_review(publisher, project)
    assert "summary_ne" in str(excinfo.value)
    project.refresh_from_db()
    assert project.status == ProjectStatus.DRAFT


@pytest.mark.integration
def test_scheduled_publication_goes_public_at_the_future_date():
    """GOV-004-I1: an approved project with a future publication date opens exactly then."""
    from datetime import timedelta

    from django.utils import timezone

    project = make_publishable()
    publisher = project.owner
    super_admin = SuperAdminFactory()
    submit_for_review(publisher, project)
    schedule_for = timezone.now() + timedelta(days=3)
    approve(super_admin, project, publish_at=schedule_for)
    project.refresh_from_db()
    assert project.status == ProjectStatus.APPROVED
    assert project.scheduled_publication_at == schedule_for

    publish_due_scheduled(now=timezone.now() + timedelta(days=1))
    project.refresh_from_db()
    assert project.status == ProjectStatus.APPROVED

    publish_due_scheduled(now=schedule_for + timedelta(hours=1))
    project.refresh_from_db()
    assert project.status == ProjectStatus.OPEN_FOR_CONTRIBUTION
    assert project.published_at is not None


@pytest.mark.integration
def test_restore_from_archive_is_super_admin_only():
    """GOV-004-I2: only a Super Admin restores an archived project, to its prior state."""
    project = make_publishable()
    publisher = project.owner
    super_admin = SuperAdminFactory()
    walk_to(project, REACHABLE[ProjectStatus.ARCHIVED], publisher, super_admin)

    with pytest.raises(ProjectAuthorizationError):
        restore(publisher, project)

    restored = restore(super_admin, project)
    project.refresh_from_db()
    assert project.status == ProjectStatus.OPEN_FOR_CONTRIBUTION
    assert restored == project
    from apps.projects.models import ProjectReview

    assert ProjectReview.objects.filter(project=project, decision="restored").exists()


@pytest.mark.integration
def test_personal_projects_use_the_restricted_subset():
    """PPR-001/PPR-006: personal listings never enter review; the owner runs open/pause/archive."""
    owner = UserFactory()
    project = PersonalProjectFactory(owner=owner)

    with pytest.raises(ProjectLifecycleError) as excinfo:
        submit_for_review(owner, project)
    assert "personal" in str(excinfo.value).lower()

    with pytest.raises(ProjectLifecycleError):
        open_personal_listing(owner, project)

    from apps.projects.services import accept_community_terms

    accept_community_terms(owner)
    open_personal_listing(owner, project)
    project.refresh_from_db()
    assert project.status == ProjectStatus.OPEN_FOR_CONTRIBUTION

    pause(owner, project)
    project.refresh_from_db()
    assert project.status == ProjectStatus.PAUSED

    with pytest.raises(ProjectAuthorizationError):
        resume(UserFactory(), project)
    resume(owner, project)
    project.refresh_from_db()
    assert project.status == ProjectStatus.OPEN_FOR_CONTRIBUTION

    complete(owner, project)
    archive(owner, project, reason="Done")
    project.refresh_from_db()
    assert project.status == ProjectStatus.ARCHIVED


@pytest.mark.integration
def test_every_transition_audited_with_before_and_after_state():
    """GOV-005/SEC-008: each lifecycle action audits an immutable before/after row."""
    project = make_publishable()
    publisher = project.owner
    super_admin = SuperAdminFactory()
    submit_for_review(publisher, project)
    request_changes(super_admin, project, reason="Add milestones")
    resubmit(publisher, project)
    approve(super_admin, project)
    publish(super_admin, project)

    pairs = list(
        AuditEvent.objects.filter(
            object_id=str(project.pk), action__startswith="project."
        ).values_list("before__status", "after__status")
    )
    assert (ProjectStatus.DRAFT, ProjectStatus.IN_REVIEW) in pairs
    assert (ProjectStatus.IN_REVIEW, ProjectStatus.CHANGES_REQUESTED) in pairs
    assert (ProjectStatus.CHANGES_REQUESTED, ProjectStatus.IN_REVIEW) in pairs
    assert (ProjectStatus.IN_REVIEW, ProjectStatus.APPROVED) in pairs
    assert (ProjectStatus.APPROVED, ProjectStatus.OPEN_FOR_CONTRIBUTION) in pairs


@pytest.mark.integration
def test_br011_closed_states_reject_new_applications():
    """BR-011-U1: paused/completed/cancelled/archived projects accept no new applications."""
    from apps.projects.services import ApplicationClosedError, apply_to_project

    for target in (
        ProjectStatus.PAUSED,
        ProjectStatus.COMPLETED,
        ProjectStatus.CANCELLED,
        ProjectStatus.ARCHIVED,
    ):
        project = make_publishable()
        publisher = project.owner
        super_admin = SuperAdminFactory()
        walk_to(project, REACHABLE[target], publisher, super_admin)
        member = UserFactory()
        with pytest.raises(ApplicationClosedError) as excinfo:
            apply_to_project(member, project)
        assert target in str(excinfo.value)


@pytest.mark.integration
def test_non_publisher_cannot_submit_and_super_admin_can_manage():
    """GOV-001/AUTH-006: a plain member cannot submit a government draft."""
    project = make_publishable()
    with pytest.raises(ProjectAuthorizationError):
        submit_for_review(UserFactory(), project)
    project.refresh_from_db()
    assert project.status == ProjectStatus.DRAFT


@pytest.mark.unit
@pytest.mark.parametrize(
    ("action", "perform"),
    [
        ("project.pause", lambda actor, project: pause(actor, project)),
        ("project.resume", lambda actor, project: resume(actor, project)),
        ("project.complete", lambda actor, project: complete(actor, project)),
        ("project.cancel", lambda actor, project: cancel(actor, project, reason="Cancelled")),
        ("project.archive", lambda actor, project: archive(actor, project, reason="Archived")),
        (
            "project.extend_deadline",
            lambda actor, project: extend_deadline(actor, project, new_deadline=project.deadline),
        ),
        (
            "project.attachment.add",
            lambda actor, project: add_attachment(
                actor,
                project,
                kind="proposal",
                file=SimpleUploadedFile(
                    "proposal.pdf", b"%PDF-1.4", content_type="application/pdf"
                ),
            ),
        ),
    ],
)
def test_unverified_super_admin_cannot_use_owner_or_super_admin_paths(action, perform):
    """AUTH-005/AUTH-007/SEC-008: unverified superadmin overrides are denied and audited."""
    project = make_publishable()
    super_admin = UserFactory(is_superuser=True, is_staff=True)
    status = project.status
    deadline = project.deadline
    attachments = project.attachments.count()

    with pytest.raises(ProjectAuthorizationError):
        perform(super_admin, project)

    project.refresh_from_db()
    assert project.status == status
    assert project.deadline == deadline
    assert project.attachments.count() == attachments
    assert AuditEvent.objects.filter(
        actor=super_admin,
        action=f"{action}.denied",
        object_id=str(project.pk),
        result="failure",
    ).exists()
