from datetime import UTC, datetime

import pytest

from apps.analytics.services import (
    MINIMUM_PUBLIC_GROUP_SIZE,
    AnalyticsEvent,
    AnalyticsEventError,
    EventName,
    aggregate_ministry_events,
    public_report,
)


def event(*, name=EventName.PROJECT_VIEWED, ministry_id=1, project_id=10):
    return AnalyticsEvent(
        name=name,
        occurred_at=datetime(2026, 9, 4, tzinfo=UTC),
        ministry_id=ministry_id,
        project_id=project_id,
    )


@pytest.mark.unit
def test_event_records_only_documented_non_personal_dimensions():
    """ANL-001: analytics events use defined fields and reject personal-data-like dimensions."""
    with pytest.raises(AnalyticsEventError, match="not permitted"):
        AnalyticsEvent(
            name=EventName.PROJECT_VIEWED,
            occurred_at=datetime(2026, 9, 4, tzinfo=UTC),
            ministry_id=1,
            project_id=10,
            dimensions={"email": "member@example.com"},
        )


@pytest.mark.unit
def test_ministry_aggregate_excludes_other_ministries_events():
    """ANL-002: a ministry aggregate contains events for its projects only."""
    aggregate = aggregate_ministry_events(
        [
            event(name=EventName.PROJECT_VIEWED),
            event(name=EventName.PROJECT_APPLIED, ministry_id=2),
        ],
        ministry_id=1,
    )

    assert aggregate.ministry_id == 1
    assert aggregate.event_counts == {EventName.PROJECT_VIEWED: 1}
    assert aggregate.project_counts == {10: 1}


@pytest.mark.unit
def test_public_report_suppresses_groups_smaller_than_five():
    """ANL-003: public reports suppress groups below the privacy threshold of five."""
    report = public_report(
        [event(project_id=10) for _ in range(4)] + [event(project_id=20) for _ in range(5)]
    )

    assert MINIMUM_PUBLIC_GROUP_SIZE == 5
    assert report.project_counts == {20: 5}
    assert report.suppressed_project_count == 1


@pytest.mark.unit
def test_public_report_exposes_no_event_records_or_personal_dimensions():
    """ANL-001/ANL-003: public output contains only safe aggregate counts."""
    report = public_report([event() for _ in range(5)])

    assert report.project_counts == {10: 5}
    assert not hasattr(report, "events")
    assert "member" not in repr(report).lower()
