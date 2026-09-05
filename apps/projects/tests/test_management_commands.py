import io
from datetime import datetime, timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.projects.enums import ProjectStatus
from apps.projects.services import create_version
from apps.projects.tests.factories import make_publishable

pytestmark = pytest.mark.django_db


@pytest.fixture
def frozen_now(monkeypatch):
    moment = timezone.make_aware(datetime(2027, 5, 10, 9, 30))
    monkeypatch.setattr(timezone, "now", lambda: moment)
    return moment


def open_project(**kwargs):
    project = make_publishable(**kwargs)
    project.status = ProjectStatus.OPEN_FOR_CONTRIBUTION
    project.save(update_fields=["status"])
    return project


def approved_scheduled(moment):
    project = make_publishable()
    create_version(project, submitted_by=project.owner)
    project.status = ProjectStatus.APPROVED
    project.scheduled_publication_at = moment
    project.save(update_fields=["status", "scheduled_publication_at"])
    return project


@pytest.mark.integration
def test_flag_stale_projects_records_expiry_and_staleness_without_closing(frozen_now):
    """GOV-010/D5: the sweep flags expired deadlines and stale maintainers; nothing auto-closes."""
    stale = open_project()
    stale.last_maintainer_activity_at = frozen_now - timedelta(days=11)
    stale.save(update_fields=["last_maintainer_activity_at"])
    expired = open_project(deadline=timezone.localdate() - timedelta(days=2))
    fresh = open_project()

    out = io.StringIO()
    call_command("flag_stale_projects", stdout=out)

    assert AuditEvent.objects.filter(
        action="project.maintainer_sla_flagged", object_id=str(stale.pk)
    ).exists()
    assert AuditEvent.objects.filter(
        action="project.deadline_expired", object_id=str(expired.pk)
    ).exists()
    assert not AuditEvent.objects.filter(
        object_id=str(fresh.pk),
        action__in=[
            "project.maintainer_sla_flagged",
            "project.deadline_expired",
        ],
    ).exists()
    for project in (stale, expired, fresh):
        project.refresh_from_db()
        assert project.status == ProjectStatus.OPEN_FOR_CONTRIBUTION
    assert "1 expired deadline" in out.getvalue()
    assert "1 stale project" in out.getvalue()


@pytest.mark.integration
def test_flag_stale_projects_is_idempotent_per_flag(frozen_now):
    """GOV-010/D5: running the sweep twice records each flag exactly once."""
    stale = open_project()
    stale.last_maintainer_activity_at = frozen_now - timedelta(days=11)
    stale.save(update_fields=["last_maintainer_activity_at"])

    call_command("flag_stale_projects")
    call_command("flag_stale_projects")

    assert (
        AuditEvent.objects.filter(
            action="project.maintainer_sla_flagged", object_id=str(stale.pk)
        ).count()
        == 1
    )


@pytest.mark.integration
def test_publish_scheduled_publishes_only_due_ready_projects(frozen_now):
    """GOV-004/D5: scheduled publications open exactly when their scheduled time arrives."""
    due = approved_scheduled(frozen_now - timedelta(days=1))
    future = approved_scheduled(frozen_now + timedelta(days=7))
    unready = approved_scheduled(frozen_now - timedelta(days=1))
    unready.maintainer_assignments.all().delete()

    out = io.StringIO()
    call_command("publish_scheduled", stdout=out)

    due.refresh_from_db()
    future.refresh_from_db()
    unready.refresh_from_db()
    assert due.status == ProjectStatus.OPEN_FOR_CONTRIBUTION
    assert due.published_at is not None
    assert due.scheduled_publication_at is None
    assert future.status == ProjectStatus.APPROVED
    assert unready.status == ProjectStatus.APPROVED
    assert "Published 1 scheduled project" in out.getvalue()
