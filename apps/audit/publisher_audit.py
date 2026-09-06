from collections.abc import Iterable
from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.audit.services import record_audit
from apps.ministries.enums import OrgStatus, PublisherStatus
from apps.ministries.models import MinistryOrganization, MinistryPublisher
from apps.projects.models import (
    Application,
    ApplicationEvent,
    Project,
    ProjectAttachment,
    ProjectLink,
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

ORGANIZATION_CATEGORY = "organization"
OFFICERS_CATEGORY = "officers"
PROJECTS_CATEGORY = "projects"
ALL_CATEGORIES = "all"
PUBLISHER_AUDIT_CATEGORIES = (
    ALL_CATEGORIES,
    ORGANIZATION_CATEGORY,
    OFFICERS_CATEGORY,
    PROJECTS_CATEGORY,
)
PUBLISHER_AUDIT_RESULTS = ("success", "failure", "denied")
PUBLISHER_EXPORT_LIMIT = 10
PUBLISHER_EXPORT_MAX_ROWS = 5000
PUBLISHER_EXPORT_MIN_PURPOSE_LENGTH = 20
PUBLISHER_EXPORT_WINDOW = timedelta(hours=1)


class PublisherAuditExportError(Exception):
    """Base failure for the purpose-limited C6.2 audit export."""


class PublisherAuditExportAuthorizationError(PublisherAuditExportError):
    """The actor cannot export the requested publisher or ministry ledger."""


class PublisherAuditExportPurposeError(PublisherAuditExportError):
    """The export lacks a meaningful declared purpose."""


class PublisherAuditExportRateLimitError(PublisherAuditExportError):
    """The publisher exceeded the bounded hourly export allowance."""


PROJECT_RESOURCE_MODELS = (
    (Project, "ministry"),
    (ProjectMaintainer, "project__ministry"),
    (ProjectVersion, "project__ministry"),
    (ProjectReview, "project__ministry"),
    (ProjectReviewAssignment, "project__ministry"),
    (ProjectSuitability, "project__ministry"),
    (ProjectScreeningQuestion, "project__ministry"),
    (ProjectTask, "project__ministry"),
    (ProjectMilestone, "project__ministry"),
    (ProjectUpdate, "project__ministry"),
    (ProjectAttachment, "project__ministry"),
    (ProjectLink, "project__ministry"),
    (Application, "project__ministry"),
    (ApplicationEvent, "application__project__ministry"),
)


def active_publisher_ministries(user) -> QuerySet[MinistryOrganization]:
    return MinistryOrganization.objects.filter(
        publishers__user=user,
        publishers__status=PublisherStatus.ACTIVE,
        status=OrgStatus.ACTIVE,
    ).distinct()


def publisher_audit_events(*, user, ministry=None, scope: str, category: str):
    from apps.audit.models import AuditEvent

    events = AuditEvent.objects.select_related("actor", "content_type").order_by("-created_at")
    if scope != "organization" or ministry is None:
        return events.filter(actor=user)

    category_filter = _ministry_resource_filter(ministry, category)
    if category == ALL_CATEGORIES:
        return events.filter(Q(actor=user) | category_filter)
    return events.filter(category_filter)


def add_event_presentation(events: Iterable) -> None:
    for event in events:
        event.basis_reason = _event_basis_reason(event)
        event.target_reference = _event_target_reference(event)


def export_publisher_audit(
    *, user, ministry=None, scope: str, category: str, result: str, purpose: str
) -> list:
    """GOV-005/ADM-005: export a bounded, re-authorized ledger and audit only metadata."""
    active_ministries = active_publisher_ministries(user)
    if not active_ministries.exists():
        raise PublisherAuditExportAuthorizationError("an active publisher role is required")
    if scope not in {"mine", "organization"}:
        raise PublisherAuditExportAuthorizationError("invalid audit scope")
    if category not in PUBLISHER_AUDIT_CATEGORIES or result not in {
        "",
        *PUBLISHER_AUDIT_RESULTS,
    }:
        raise PublisherAuditExportAuthorizationError("invalid audit filter")
    if scope == "organization":
        if ministry is None or not active_ministries.filter(pk=ministry.pk).exists():
            raise PublisherAuditExportAuthorizationError("organization is outside publisher scope")
    else:
        ministry = None
        category = ALL_CATEGORIES

    cleaned_purpose = " ".join((purpose or "").split())
    if len(cleaned_purpose) < PUBLISHER_EXPORT_MIN_PURPOSE_LENGTH:
        record_audit(
            actor=user,
            action="audit.publisher_export.denied",
            obj=ministry or user,
            after={"reason": "purpose_required"},
            result="failure",
        )
        raise PublisherAuditExportPurposeError("a specific export purpose is required")
    recent_exports = user.audit_events.filter(
        action="audit.publisher_export",
        created_at__gte=timezone.now() - PUBLISHER_EXPORT_WINDOW,
    ).count()
    if recent_exports >= PUBLISHER_EXPORT_LIMIT:
        record_audit(
            actor=user,
            action="audit.publisher_export.denied",
            obj=ministry or user,
            after={"reason": "rate_limited"},
            result="failure",
        )
        raise PublisherAuditExportRateLimitError("hourly publisher export limit reached")

    events = publisher_audit_events(
        user=user,
        ministry=ministry,
        scope=scope,
        category=category,
    )
    if result:
        events = events.filter(result=result)
    rows = list(events[:PUBLISHER_EXPORT_MAX_ROWS])
    add_event_presentation(rows)
    record_audit(
        actor=user,
        action="audit.publisher_export",
        obj=ministry or user,
        after={
            "purpose": cleaned_purpose,
            "count": len(rows),
            "scope": scope,
            "ministry_id": ministry.pk if ministry else None,
            "category": category,
            "result": result,
        },
    )
    return rows


def _ministry_resource_filter(ministry, category: str) -> Q:
    resource_ids = _ministry_resource_ids(ministry)
    categories = (
        (ORGANIZATION_CATEGORY,)
        if category == ORGANIZATION_CATEGORY
        else (OFFICERS_CATEGORY,)
        if category == OFFICERS_CATEGORY
        else (PROJECTS_CATEGORY,)
        if category == PROJECTS_CATEGORY
        else (ORGANIZATION_CATEGORY, OFFICERS_CATEGORY, PROJECTS_CATEGORY)
    )
    resource_filter = Q(pk__in=[])
    for name in categories:
        for content_type_id, object_ids in resource_ids[name].items():
            resource_filter |= Q(content_type_id=content_type_id, object_id__in=object_ids)
    return resource_filter


def _ministry_resource_ids(ministry) -> dict[str, dict[int, list[str]]]:
    content_types = ContentType.objects.get_for_models(
        MinistryOrganization,
        MinistryPublisher,
        *(model for model, _ in PROJECT_RESOURCE_MODELS),
    )
    project_resource_ids = {}
    for model, ministry_lookup in PROJECT_RESOURCE_MODELS:
        project_resource_ids[content_types[model].pk] = _as_strings(
            model.objects.filter(**{ministry_lookup: ministry}).values_list("pk", flat=True)
        )
    return {
        ORGANIZATION_CATEGORY: {content_types[MinistryOrganization].pk: [str(ministry.pk)]},
        OFFICERS_CATEGORY: {
            content_types[MinistryPublisher].pk: _as_strings(
                MinistryPublisher.objects.filter(ministry=ministry).values_list("pk", flat=True)
            )
        },
        PROJECTS_CATEGORY: project_resource_ids,
    }


def _as_strings(values: Iterable) -> list[str]:
    return [str(value) for value in values]


def _event_basis_reason(event) -> str:
    for values in (event.after, event.before):
        if not isinstance(values, dict):
            continue
        for key in ("reason", "basis", "note", "comment", "revocation_reason"):
            value = values.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _event_target_reference(event) -> str:
    if event.content_type is None:
        return ""
    if not event.object_id:
        return event.content_type.name
    return f"{event.content_type.name} #{event.object_id}"
