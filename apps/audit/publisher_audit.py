from collections.abc import Iterable

from django.contrib.contenttypes.models import ContentType
from django.db.models import Q, QuerySet

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
