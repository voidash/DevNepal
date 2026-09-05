"""Privacy-preserving analytics persistence, aggregation, and monthly reporting."""

import logging
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time

from django.db import IntegrityError, transaction
from django.db.models import Count, QuerySet
from django.utils import timezone

from apps.analytics.enums import EventName
from apps.analytics.models import AnalyticsEventRecord
from apps.ministries.enums import OrgStatus, PublisherStatus
from apps.ministries.models import MinistryPublisher

logger = logging.getLogger(__name__)

MINIMUM_PUBLIC_GROUP_SIZE = 5
SOURCE_REF_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")
PUBLIC_REPORT_SOURCE = "DevNepal privacy-safe aggregate analytics"
PUBLIC_REPORT_USAGE_NOTICE = (
    "Public aggregate data only. Do not attempt to identify or re-identify any individual."
)


@dataclass(frozen=True)
class EventDefinition:
    """ANL-001: documented, non-personal analytics event schema."""

    name: EventName
    description: str
    dimensions: frozenset[str]


EVENT_DEFINITIONS: Mapping[EventName, EventDefinition] = {
    EventName.PROJECT_VIEWED: EventDefinition(
        name=EventName.PROJECT_VIEWED,
        description="A project detail page was viewed.",
        dimensions=frozenset(),
    ),
    EventName.PROJECT_APPLIED: EventDefinition(
        name=EventName.PROJECT_APPLIED,
        description="A project application was submitted.",
        dimensions=frozenset(),
    ),
    EventName.CONTRIBUTION_ACCEPTED: EventDefinition(
        name=EventName.CONTRIBUTION_ACCEPTED,
        description="A contribution record was accepted.",
        dimensions=frozenset(),
    ),
}


class AnalyticsError(Exception):
    """Base error for analytics persistence and reporting."""


class AnalyticsEventError(AnalyticsError, ValueError):
    """An analytics event violates the documented privacy-safe schema."""


class AnalyticsEventConflictError(AnalyticsError):
    """An integration source reference was reused for a different analytics event."""


class AnalyticsPersistenceError(AnalyticsError):
    """A validated analytics event could not be persisted."""


class AnalyticsAuthorizationError(AnalyticsError):
    """The actor cannot view analytics for the requested ministry."""


class AnalyticsReportPeriodError(AnalyticsError, ValueError):
    """A requested reporting month is invalid."""


@dataclass(frozen=True)
class AnalyticsEvent:
    """ANL-001: an event containing only a metric name and project ownership identifiers."""

    name: EventName
    occurred_at: datetime
    ministry_id: int
    project_id: int
    dimensions: Mapping[str, str | int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _event_name(self.name)
        _require_aware(self.occurred_at)
        _validate_identifier("ministry_id", self.ministry_id)
        _validate_identifier("project_id", self.project_id)
        allowed_dimensions = EVENT_DEFINITIONS[_event_name(self.name)].dimensions
        invalid_dimensions = sorted(set(self.dimensions) - allowed_dimensions)
        if invalid_dimensions:
            raise AnalyticsEventError(
                f"analytics dimensions are not permitted: {', '.join(invalid_dimensions)}"
            )
        for value in self.dimensions.values():
            if not isinstance(value, (str, int)) or isinstance(value, bool):
                raise AnalyticsEventError("analytics dimension values must be strings or integers")


@dataclass(frozen=True)
class MinistryAggregate:
    """ANL-002: aggregate metrics strictly scoped to one ministry."""

    ministry_id: int
    event_counts: Mapping[EventName, int]
    project_counts: Mapping[int, int]


@dataclass(frozen=True)
class PublicReport:
    """ANL-003: public aggregate metrics after small-group suppression."""

    event_counts: Mapping[EventName, int]
    ministry_counts: Mapping[int, int]
    project_counts: Mapping[int, int]
    suppressed_event_count: int
    suppressed_ministry_count: int
    suppressed_project_count: int


@dataclass(frozen=True)
class MonthlyPublicReport:
    """ANL-003/ANL-004: privacy-safe monthly report with export provenance."""

    report_month: date
    generated_at: datetime
    aggregate: PublicReport

    def export_payload(self) -> dict:
        return {
            "source": PUBLIC_REPORT_SOURCE,
            "generated_at": self.generated_at.isoformat(),
            "filters": {"month": self.report_month.strftime("%Y-%m")},
            "field_definitions": [
                {
                    "name": "event_counts",
                    "description": "Counts by documented event name after suppression.",
                },
                {
                    "name": "suppressed_group_counts",
                    "description": (
                        "Number of event, ministry, or project groups withheld for privacy."
                    ),
                },
            ],
            "usage_notice": PUBLIC_REPORT_USAGE_NOTICE,
            "event_counts": {
                name.value: count for name, count in self.aggregate.event_counts.items()
            },
            "suppressed_group_counts": {
                "event": self.aggregate.suppressed_event_count,
                "ministry": self.aggregate.suppressed_ministry_count,
                "project": self.aggregate.suppressed_project_count,
            },
        }


def record_event(
    name: EventName | str,
    *,
    project,
    occurred_at: datetime | None = None,
    source_ref: str = "",
) -> AnalyticsEventRecord:
    """ANL-001: persist a privacy-minimized, project-owned analytics event."""
    event_name = _event_name(name)
    project_id = getattr(project, "pk", None)
    ministry_id = getattr(project, "ministry_id", None)
    _validate_identifier("project_id", project_id)
    _validate_identifier("ministry_id", ministry_id)
    occurred = occurred_at or timezone.now()
    _require_aware(occurred)
    clean_source_ref = _source_ref(source_ref)
    if clean_source_ref:
        existing = AnalyticsEventRecord.objects.filter(source_ref=clean_source_ref).first()
        if existing is not None:
            return _matching_source_record(existing, event_name, ministry_id, project_id)
    try:
        with transaction.atomic():
            return AnalyticsEventRecord.objects.create(
                event_name=event_name,
                ministry_id=ministry_id,
                project_id=project_id,
                occurred_at=occurred,
                source_ref=clean_source_ref,
            )
    except IntegrityError as exc:
        if clean_source_ref:
            existing = AnalyticsEventRecord.objects.filter(source_ref=clean_source_ref).first()
            if existing is not None:
                return _matching_source_record(existing, event_name, ministry_id, project_id)
        logger.exception(
            "Analytics event persistence failed; event_name=%s ministry_id=%s project_id=%s",
            event_name,
            ministry_id,
            project_id,
        )
        raise AnalyticsPersistenceError("analytics event could not be persisted") from exc


def aggregate_ministry_events(
    events: list[AnalyticsEvent], *, ministry_id: int
) -> MinistryAggregate:
    """ANL-002: return only metrics belonging to the requested ministry."""
    _validate_identifier("ministry_id", ministry_id)
    scoped_events = [event for event in events if event.ministry_id == ministry_id]
    return MinistryAggregate(
        ministry_id=ministry_id,
        event_counts=dict(Counter(_event_name(event.name) for event in scoped_events)),
        project_counts=dict(Counter(event.project_id for event in scoped_events)),
    )


def monthly_ministry_aggregate(ministry, *, month: date) -> MinistryAggregate:
    """ANL-002: aggregate a single ministry's persisted events for one calendar month."""
    ministry_id = getattr(ministry, "pk", None)
    _validate_identifier("ministry_id", ministry_id)
    events = _month_queryset(month).filter(ministry_id=ministry_id)
    return MinistryAggregate(
        ministry_id=ministry_id,
        event_counts=_event_counts(events),
        project_counts=_project_counts(events),
    )


def public_report(events: list[AnalyticsEvent]) -> PublicReport:
    """ANL-003: report only aggregate groups meeting the minimum public size."""
    return _public_report_from_counts(
        Counter(_event_name(event.name) for event in events),
        Counter(event.ministry_id for event in events),
        Counter(event.project_id for event in events),
    )


def monthly_public_report(*, month: date) -> MonthlyPublicReport:
    """ANL-003/ANL-004: create a self-describing public aggregate report for one month."""
    events = _month_queryset(month)
    return MonthlyPublicReport(
        report_month=_report_month(month),
        generated_at=timezone.now(),
        aggregate=_public_report_from_counts(
            _event_counts(events),
            _ministry_counts(events),
            _project_counts(events),
        ),
    )


def authorize_ministry_analytics(actor, ministry) -> None:
    """ANL-002: restrict ministry aggregates to active named publishers or Super Admins."""
    ministry_id = getattr(ministry, "pk", None)
    _validate_identifier("ministry_id", ministry_id)
    active_super_admin = bool(
        actor
        and getattr(actor, "is_authenticated", False)
        and getattr(actor, "is_active", False)
        and getattr(actor, "is_superuser", False)
    )
    active_publisher = bool(
        actor
        and getattr(actor, "is_authenticated", False)
        and getattr(actor, "is_active", False)
        and MinistryPublisher.objects.filter(
            user=actor,
            ministry_id=ministry_id,
            status=PublisherStatus.ACTIVE,
            ministry__status=OrgStatus.ACTIVE,
        ).exists()
    )
    if active_super_admin or active_publisher:
        return
    logger.warning(
        "Denied ministry analytics access; actor_id=%s ministry_id=%s",
        getattr(actor, "pk", None),
        ministry_id,
    )
    raise AnalyticsAuthorizationError("analytics access is limited to the owning ministry")


def _matching_source_record(
    record: AnalyticsEventRecord,
    event_name: EventName,
    ministry_id: int,
    project_id: int,
) -> AnalyticsEventRecord:
    if (
        record.event_name == event_name
        and record.ministry_id == ministry_id
        and record.project_id == project_id
    ):
        return record
    logger.warning(
        "Conflicting analytics source reference; existing_event_id=%s ministry_id=%s project_id=%s",
        record.event_id,
        ministry_id,
        project_id,
    )
    raise AnalyticsEventConflictError("analytics source reference belongs to a different event")


def _event_name(value: EventName | str) -> EventName:
    try:
        return EventName(value)
    except (TypeError, ValueError) as exc:
        raise AnalyticsEventError("analytics event name is not documented") from exc


def _source_ref(value: str) -> str:
    if not isinstance(value, str):
        raise AnalyticsEventError("analytics source reference must be a string")
    clean_value = value.strip()
    if len(clean_value) > 120:
        raise AnalyticsEventError("analytics source reference exceeds 120 characters")
    if clean_value and not SOURCE_REF_PATTERN.fullmatch(clean_value):
        raise AnalyticsEventError("analytics source reference must be an opaque identifier")
    return clean_value


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AnalyticsEventError("analytics event timestamps must be timezone-aware")


def _validate_identifier(name: str, value: int | None) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise AnalyticsEventError(f"{name} must be a positive integer")


def _report_month(value: date) -> date:
    if not isinstance(value, date) or isinstance(value, datetime) or value.day != 1:
        raise AnalyticsReportPeriodError(
            "reporting month must be the first day of a calendar month"
        )
    return value


def _month_queryset(month: date) -> QuerySet[AnalyticsEventRecord]:
    report_month = _report_month(month)
    if report_month.month == 12:
        following_month = date(report_month.year + 1, 1, 1)
    else:
        following_month = date(report_month.year, report_month.month + 1, 1)
    current_timezone = timezone.get_current_timezone()
    starts_at = timezone.make_aware(datetime.combine(report_month, time.min), current_timezone)
    ends_at = timezone.make_aware(datetime.combine(following_month, time.min), current_timezone)
    return AnalyticsEventRecord.objects.filter(occurred_at__gte=starts_at, occurred_at__lt=ends_at)


def _event_counts(events: QuerySet[AnalyticsEventRecord]) -> dict[EventName, int]:
    return {
        EventName(row["event_name"]): row["total"]
        for row in events.values("event_name").annotate(total=Count("id"))
    }


def _ministry_counts(events: QuerySet[AnalyticsEventRecord]) -> dict[int, int]:
    return {
        row["ministry_id"]: row["total"]
        for row in events.values("ministry_id").annotate(total=Count("id"))
    }


def _project_counts(events: QuerySet[AnalyticsEventRecord]) -> dict[int, int]:
    return {
        row["project_id"]: row["total"]
        for row in events.values("project_id").annotate(total=Count("id"))
    }


def _public_report_from_counts(
    event_counts: Mapping[EventName, int],
    ministry_counts: Mapping[int, int],
    project_counts: Mapping[int, int],
) -> PublicReport:
    public_event_counts, suppressed_event_count = _suppress(event_counts)
    public_ministry_counts, suppressed_ministry_count = _suppress(ministry_counts)
    public_project_counts, suppressed_project_count = _suppress(project_counts)
    return PublicReport(
        event_counts=public_event_counts,
        ministry_counts=public_ministry_counts,
        project_counts=public_project_counts,
        suppressed_event_count=suppressed_event_count,
        suppressed_ministry_count=suppressed_ministry_count,
        suppressed_project_count=suppressed_project_count,
    )


def _suppress(counts: Mapping) -> tuple[dict, int]:
    visible = {key: count for key, count in counts.items() if count >= MINIMUM_PUBLIC_GROUP_SIZE}
    return visible, len(counts) - len(visible)
