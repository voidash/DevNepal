from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.tests.factories import attach_otp_verification
from apps.audit.models import AuditEvent
from apps.projects.enums import MilestoneStatus, ProjectStatus, UpdateKind
from apps.projects.services import (
    ProjectAuthorizationError,
    deadline_expired,
    extend_deadline,
    flag_expired,
    flag_stale,
    maintainer_response_stale,
    pause,
    post_update,
)
from apps.projects.tests.factories import (
    ProjectFactory,
    ProjectMilestoneFactory,
    ProjectUpdateFactory,
    UserFactory,
    make_publishable,
)

pytestmark = [pytest.mark.django_db]


@pytest.mark.unit
def test_progress_update_records_kind_author_and_link():
    """GOV-009: progress updates capture title, body, kind, link, and author."""
    author = UserFactory()
    update = ProjectUpdateFactory(
        created_by=author,
        kind=UpdateKind.PROGRESS,
        link="https://github.com/org/repo/releases/v1",
    )
    fetched = type(update).objects.get(pk=update.pk)
    assert fetched.kind == UpdateKind.PROGRESS
    assert fetched.created_by == author
    assert fetched.project.updates.count() == 1


@pytest.mark.unit
def test_completion_summary_is_a_first_class_update_kind():
    """GOV-009: a completion summary is a distinct update kind for closure."""
    update = ProjectUpdateFactory(kind=UpdateKind.COMPLETION, title="Final outcome")
    assert update.kind == UpdateKind.COMPLETION


@pytest.mark.unit
def test_milestone_tracks_status_and_completion():
    """GOV-009/GOV-002: milestones track status ordering and completion stamps."""
    project = ProjectFactory()
    planned = ProjectMilestoneFactory(project=project, sort_order=1, status=MilestoneStatus.PLANNED)
    achieved = ProjectMilestoneFactory(
        project=project, sort_order=2, status=MilestoneStatus.ACHIEVED
    )
    milestones = list(project.milestones.all())
    assert milestones == [planned, achieved]
    assert achieved.status == MilestoneStatus.ACHIEVED


# ---------------------------------------------------------------------------
# Updates, deadlines, SLA staleness services (GOV-009, GOV-010, GOV-012)


def open_project(**kwargs):
    project = make_publishable(**kwargs)
    project.status = ProjectStatus.OPEN_FOR_CONTRIBUTION
    project.save(update_fields=["status"])
    return project


@pytest.mark.integration
def test_publisher_posts_progress_and_completion_updates():
    """GOV-009-I1: the publisher posts progress/release updates and a completion summary."""
    project = open_project()
    publisher = project.owner

    progress = post_update(
        publisher, project, title="Sprint 4 done", body="Search shipped.", kind=UpdateKind.PROGRESS
    )
    release = post_update(
        publisher,
        project,
        title="v1 released",
        body="First release.",
        kind=UpdateKind.RELEASE,
        link="https://github.com/moit/repo/releases/v1.0",
    )
    summary = post_update(
        publisher,
        project,
        title="Project completed",
        body="Outcome delivered; thanks to all contributors.",
        kind=UpdateKind.COMPLETION,
    )

    assert [progress.kind, release.kind, summary.kind] == [
        UpdateKind.PROGRESS,
        UpdateKind.RELEASE,
        UpdateKind.COMPLETION,
    ]
    assert release.link.startswith("https://")

    with pytest.raises(ProjectAuthorizationError):
        post_update(UserFactory(), project, title="Noise", body="Nope")


@pytest.mark.integration
def test_expired_deadline_never_auto_closes_the_project():
    """GOV-010-U1: a passed deadline raises a flag but changes no state."""
    project = open_project(deadline=timezone.localdate() - timedelta(days=5))

    assert deadline_expired(project) is True
    flagged = flag_expired(project)
    flagged_again = flag_expired(project)

    assert flagged is True
    assert flagged_again is True
    project.refresh_from_db()
    assert project.status == ProjectStatus.OPEN_FOR_CONTRIBUTION
    assert (
        AuditEvent.objects.filter(
            action="project.deadline_expired", object_id=str(project.pk)
        ).count()
        == 1
    )


@pytest.mark.integration
def test_owner_must_act_explicitly_after_deadline_expiry():
    """GOV-010-I1: after expiry the owner acts explicitly (extend/pause/close)."""
    project = open_project(deadline=timezone.localdate() - timedelta(days=1))
    flag_expired(project)

    extend_deadline(project.owner, project, timezone.localdate() + timedelta(days=30))
    project.refresh_from_db()
    attach_otp_verification(project.owner)
    assert project.deadline == timezone.localdate() + timedelta(days=30)
    assert deadline_expired(project) is False
    assert AuditEvent.objects.filter(
        action="project.deadline_extended", object_id=str(project.pk)
    ).exists()

    pause(project.owner, project)
    project.refresh_from_db()
    assert project.status == ProjectStatus.PAUSED

    with pytest.raises(ProjectAuthorizationError):
        extend_deadline(UserFactory(), project, timezone.localdate() + timedelta(days=1))


@pytest.mark.integration
def test_maintainer_non_response_past_sla_creates_flag():
    """GOV-012/D5: no maintainer response beyond twice the default 5-day SLA flags the project."""
    project = open_project()
    project.last_maintainer_activity_at = timezone.now() - timedelta(days=11)
    project.save(update_fields=["last_maintainer_activity_at"])

    assert maintainer_response_stale(project) is True
    assert flag_stale(project) is True
    assert flag_stale(project) is True
    assert (
        AuditEvent.objects.filter(
            action="project.maintainer_sla_flagged", object_id=str(project.pk)
        ).count()
        == 1
    )

    fresh = open_project()
    fresh.last_maintainer_activity_at = timezone.now() - timedelta(days=3)
    fresh.save(update_fields=["last_maintainer_activity_at"])
    assert maintainer_response_stale(fresh) is False
    assert flag_stale(fresh) is False
