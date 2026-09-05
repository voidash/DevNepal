from datetime import UTC, date, datetime

import pytest
from django.utils import timezone

from apps.analytics.enums import EventName
from apps.analytics.models import AnalyticsEventRecord
from apps.analytics.services import (
    AnalyticsEventConflictError,
    AnalyticsEventError,
    monthly_ministry_aggregate,
    monthly_public_report,
    record_event,
)
from apps.ministries.tests.factories import MinistryOrganizationFactory
from apps.projects.tests.factories import PersonalProjectFactory, ProjectFactory

pytestmark = pytest.mark.django_db


@pytest.mark.integration
def test_record_event_persists_only_documented_project_aggregate_data():
    """ANL-001: persisted analytics events contain documented project aggregate fields only."""
    project = ProjectFactory()
    occurred_at = datetime(2026, 9, 4, 7, 30, tzinfo=UTC)

    record = record_event(EventName.PROJECT_VIEWED, project=project, occurred_at=occurred_at)

    assert record.event_name == EventName.PROJECT_VIEWED
    assert record.ministry_id == project.ministry_id
    assert record.project_id == project.pk
    assert record.occurred_at == occurred_at
    assert set(record.__dict__) >= {"event_name", "ministry_id", "project_id", "occurred_at"}
    assert not {"member_id", "email", "payload"} & set(record.__dict__)


@pytest.mark.integration
def test_record_event_is_idempotent_for_a_source_reference():
    """ANL-001: integration callers can safely retry a source event without duplicate analytics."""
    project = ProjectFactory()

    first = record_event(EventName.PROJECT_APPLIED, project=project, source_ref="application:42")
    duplicate = record_event(
        EventName.PROJECT_APPLIED,
        project=project,
        source_ref="application:42",
    )

    assert first.pk == duplicate.pk
    assert AnalyticsEventRecord.objects.count() == 1


@pytest.mark.integration
def test_record_event_rejects_conflicting_source_reference():
    """ANL-001: a reused integration reference cannot silently rewrite analytics provenance."""
    project = ProjectFactory()
    other_project = ProjectFactory()
    record_event(EventName.PROJECT_APPLIED, project=project, source_ref="application:42")

    with pytest.raises(AnalyticsEventConflictError, match="source reference"):
        record_event(EventName.PROJECT_APPLIED, project=other_project, source_ref="application:42")


@pytest.mark.integration
def test_record_event_rejects_projects_without_a_ministry():
    """ANL-002: ministry-scoped analytics never assigns a personal project to a ministry."""
    project = PersonalProjectFactory()

    with pytest.raises(AnalyticsEventError, match="ministry"):
        record_event(EventName.PROJECT_VIEWED, project=project)


@pytest.mark.integration
def test_record_event_rejects_personal_data_in_integration_reference():
    """ANL-001: integration provenance is opaque, never an email or free-text payload."""
    project = ProjectFactory()

    with pytest.raises(AnalyticsEventError, match="opaque"):
        record_event(EventName.PROJECT_VIEWED, project=project, source_ref="member@example.com")


@pytest.mark.integration
def test_monthly_ministry_aggregate_excludes_other_ministries_and_months():
    """ANL-002: ministry reporting includes only its own events in the selected month."""
    ministry = MinistryOrganizationFactory()
    project = ProjectFactory(ministry=ministry)
    other_project = ProjectFactory()
    record_event(
        EventName.PROJECT_VIEWED,
        project=project,
        occurred_at=datetime(2026, 9, 4, 7, 30, tzinfo=UTC),
    )
    record_event(
        EventName.PROJECT_APPLIED,
        project=other_project,
        occurred_at=datetime(2026, 9, 4, 7, 30, tzinfo=UTC),
    )
    record_event(
        EventName.CONTRIBUTION_ACCEPTED,
        project=project,
        occurred_at=datetime(2026, 10, 1, 0, 0, tzinfo=UTC),
    )

    aggregate = monthly_ministry_aggregate(ministry, month=date(2026, 9, 1))

    assert aggregate.event_counts == {EventName.PROJECT_VIEWED: 1}
    assert aggregate.project_counts == {project.pk: 1}


@pytest.mark.integration
def test_monthly_public_report_suppresses_small_groups_and_has_no_records():
    """ANL-003: public monthly reports suppress groups smaller than the privacy threshold."""
    project = ProjectFactory()
    visible = ProjectFactory(ministry=project.ministry)
    month = date(2026, 9, 1)
    for _ in range(4):
        record_event(EventName.PROJECT_VIEWED, project=project)
    for _ in range(5):
        record_event(EventName.PROJECT_APPLIED, project=visible)

    report = monthly_public_report(month=month)

    assert report.aggregate.event_counts == {EventName.PROJECT_APPLIED: 5}
    assert report.aggregate.project_counts == {visible.pk: 5}
    assert report.aggregate.suppressed_project_count == 1
    assert not hasattr(report, "records")
    assert report.generated_at <= timezone.now()


@pytest.mark.integration
def test_monthly_public_export_is_self_describing_and_hides_internal_group_ids():
    """ANL-004: monthly public exports include provenance and use guidance without private IDs."""
    project = ProjectFactory()
    for _ in range(5):
        record_event(EventName.PROJECT_VIEWED, project=project)

    payload = monthly_public_report(month=date(2026, 9, 1)).export_payload()

    assert payload["source"] == "DevNepal privacy-safe aggregate analytics"
    assert payload["filters"] == {"month": "2026-09"}
    assert payload["field_definitions"]
    assert payload["usage_notice"]
    assert payload["event_counts"] == {EventName.PROJECT_VIEWED: 5}
    assert "project_counts" not in payload
    assert "ministry_counts" not in payload
