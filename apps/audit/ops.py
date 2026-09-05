from datetime import timedelta
from statistics import median

from django.db.models import Count
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.audit.models import AuditEvent
from apps.contributions.enums import VerificationStatus
from apps.contributions.models import ContributionRecord
from apps.github_sync.enums import ProcessingState, SyncState
from apps.github_sync.models import ProviderEvent, RepositoryConnection
from apps.ministries.enums import OrgStatus
from apps.ministries.models import MinistryOrganization
from apps.moderation.enums import CaseStatus
from apps.moderation.models import ModerationCase
from apps.notifications.enums import DeliveryStatus
from apps.notifications.models import Notification
from apps.projects.enums import ApplicationEventType, ApplicationStatus, ProjectStatus
from apps.projects.models import Application, ApplicationEvent, Project
from apps.projects.services import response_sla_days

PANEL_ROW_LIMIT = 5
PANEL_FETCH_LIMIT = PANEL_ROW_LIMIT + 1
AGING_CASE_DAYS = 5
AUDIT_WINDOW_HOURS = 24
STATE_CLASSES = {"ok": "", "attention": "is-attention", "danger": "is-danger"}
AVAILABILITY_PROBE_ACTION = "ops.availability_probe"
AVAILABILITY_WINDOW_DAYS = 30


def _bounded_rows(queryset):
    rows = list(queryset[:PANEL_FETCH_LIMIT])
    overflow = len(rows) > PANEL_ROW_LIMIT
    return rows[:PANEL_ROW_LIMIT], overflow


def _panel(*, panel_id, title, url, state, banner, rows, overflow, count, **extra):
    panel = {
        "id": panel_id,
        "title": title,
        "url": url,
        "state": state,
        "state_class": STATE_CLASSES[state],
        "banner": banner,
        "rows": rows,
        "overflow": overflow,
        "count": count,
    }
    panel.update(extra)
    return panel


def _stale_projects_panel():
    rows, overflow = _bounded_rows(
        Project.objects.filter(
            status__in=(ProjectStatus.PAUSED, ProjectStatus.OPEN_FOR_CONTRIBUTION),
            deadline__lt=timezone.localdate(),
        )
        .select_related("ministry")
        .order_by("deadline", "pk")
    )
    return _panel(
        panel_id="stale_projects",
        title=_("Stale or expired projects"),
        url=reverse("projects:list"),
        state="attention" if rows else "ok",
        banner=_("Projects remain publicly listed while past their deadline."),
        rows=rows,
        overflow=overflow,
        count=None if overflow else len(rows),
    )


def _aging_cases_panel():
    threshold = timezone.now() - timedelta(days=AGING_CASE_DAYS)
    rows, overflow = _bounded_rows(
        ModerationCase.objects.filter(
            status__in=(CaseStatus.NEW, CaseStatus.UNDER_REVIEW),
            created_at__lt=threshold,
        )
        .select_related("report")
        .order_by("created_at", "pk")
    )
    return _panel(
        panel_id="aging_cases",
        title=_("Aging moderation cases"),
        url=reverse("moderation:case_queue"),
        state="attention" if rows else "ok",
        banner=_("Moderation cases have been waiting longer than five days."),
        rows=rows,
        overflow=overflow,
        count=None if overflow else len(rows),
    )


def _repo_health_panel():
    rows, overflow = _bounded_rows(
        RepositoryConnection.objects.filter(sync_state__in=(SyncState.DEGRADED, SyncState.ERROR))
        .select_related("project")
        .order_by("-sync_state", "full_name")
    )
    pending_events = ProviderEvent.objects.filter(processing_state=ProcessingState.PENDING).count()
    has_error = bool(rows) and rows[0].sync_state == SyncState.ERROR
    if has_error:
        state = "danger"
    elif rows or pending_events:
        state = "attention"
    else:
        state = "ok"
    return _panel(
        panel_id="repo_health",
        title=_("Repository sync health"),
        url=reverse("github_sync:connection"),
        state=state,
        banner=_("Repository synchronization is failing or events are stacking up."),
        rows=rows,
        overflow=overflow,
        count=None if overflow else len(rows),
        pending_events=pending_events,
    )


def _notification_delivery_panel():
    breakdown = list(
        Notification.objects.filter(
            delivery_status__in=(DeliveryStatus.PENDING, DeliveryStatus.FAILED)
        )
        .values("delivery_status")
        .annotate(total=Count("id"))
        .order_by("delivery_status")
    )
    rows = [
        {
            "status": DeliveryStatus(entry["delivery_status"]),
            "label": DeliveryStatus(entry["delivery_status"]).label,
            "total": entry["total"],
        }
        for entry in breakdown
    ]
    count = sum(entry["total"] for entry in breakdown)
    return _panel(
        panel_id="notification_delivery",
        title=_("Notification delivery backlog"),
        url=reverse("notifications:list"),
        state="attention" if count else "ok",
        banner=_("Notifications are undelivered or failing to send."),
        rows=rows,
        overflow=False,
        count=count,
    )


def _recent_audit_failures_panel():
    since = timezone.now() - timedelta(hours=AUDIT_WINDOW_HOURS)
    rows, overflow = _bounded_rows(
        AuditEvent.objects.filter(result__in=("failure", "denied"), created_at__gte=since)
        .select_related("actor", "content_type")
        .order_by("result", "-created_at")
    )
    has_denied = bool(rows) and rows[0].result == "denied"
    log_url = reverse("audit:audit_log")
    if has_denied:
        state = "danger"
    elif rows:
        state = "attention"
    else:
        state = "ok"
    return _panel(
        panel_id="recent_audit_failures",
        title=_("Recent audit failures and denials"),
        url=log_url,
        state=state,
        banner=_("Audit events failed or were denied in the last 24 hours."),
        rows=rows,
        overflow=overflow,
        count=None if overflow else len(rows),
        failure_url=f"{log_url}?result=failure",
        denied_url=f"{log_url}?result=denied",
    )


def _applications_past_sla_tile(now):
    applications = Application.objects.filter(status=ApplicationStatus.SUBMITTED).select_related(
        "project__ministry"
    )
    overdue = [
        application
        for application in applications
        if now - application.submitted_at > timedelta(days=response_sla_days(application.project))
    ]
    if not overdue:
        detail = _("No submitted applications are past their published first-response window.")
    else:
        oldest = max((now - application.submitted_at).days for application in overdue)
        ministry_count = len(
            {
                application.project.ministry_id
                for application in overdue
                if application.project.ministry_id
            }
        )
        detail = _("%(ministries)s ministries · oldest %(days)s days") % {
            "ministries": ministry_count,
            "days": oldest,
        }
    return {
        "id": "applications_past_sla",
        "title": _("Applications past SLA"),
        "count": len(overdue),
        "detail": detail,
        "url": reverse("projects:application_list"),
    }


def _stale_projects_tile(now):
    projects = Project.objects.filter(
        status__in=(ProjectStatus.PAUSED, ProjectStatus.OPEN_FOR_CONTRIBUTION)
    ).select_related("ministry")
    stale = []
    for project in projects:
        anchor = project.last_maintainer_activity_at or project.published_at
        if anchor is not None and now - anchor > timedelta(days=response_sla_days(project)):
            stale.append((project, anchor))
    if not stale:
        detail = _("Every live project has activity within its published response window.")
    else:
        oldest_project, oldest_anchor = min(stale, key=lambda entry: entry[1])
        ministry = (
            oldest_project.ministry.abbreviation or oldest_project.ministry.localized_name
            if oldest_project.ministry is not None
            else _("Community")
        )
        detail = _("oldest %(days)s days · %(ministry)s") % {
            "days": (now - oldest_anchor).days,
            "ministry": ministry,
        }
    return {
        "id": "stale_projects",
        "title": _("Stale projects · no maintainer reply > SLA"),
        "count": len(stale),
        "detail": detail,
        "url": reverse("projects:list"),
    }


def _sync_failures_tile():
    failures = RepositoryConnection.objects.filter(sync_state=SyncState.ERROR).select_related(
        "project"
    )
    oldest = failures.order_by("last_synced_at", "pk").first()
    if oldest is None:
        detail = _("No GitHub App synchronization failures.")
    elif oldest.last_synced_at is None:
        detail = _("%(repository)s has never completed a sync.") % {"repository": oldest.full_name}
    else:
        detail = _("%(repository)s · failing since %(timestamp)s") % {
            "repository": oldest.full_name,
            "timestamp": timezone.localtime(oldest.last_synced_at).strftime("%Y-%m-%d %H:%M"),
        }
    return {
        "id": "sync_failures",
        "title": _("Sync failures · GitHub App"),
        "count": failures.count(),
        "detail": detail,
        "url": reverse("github_sync:connection"),
    }


def _open_queues_tile():
    review_count = Project.objects.filter(status=ProjectStatus.IN_REVIEW).count()
    report_count = ModerationCase.objects.filter(
        status__in=(CaseStatus.NEW, CaseStatus.UNDER_REVIEW, CaseStatus.ESCALATED)
    ).count()
    verification_count = ContributionRecord.objects.filter(
        status__in=(VerificationStatus.CANDIDATE, VerificationStatus.PENDING_INFO)
    ).count()
    return {
        "id": "open_queues",
        "title": _("Open queues"),
        "count": review_count + report_count + verification_count,
        "detail": _("%(reviews)s review · %(reports)s reports · %(verifications)s verification")
        % {
            "reviews": review_count,
            "reports": report_count,
            "verifications": verification_count,
        },
        "url": reverse("projects:review_queue"),
    }


def build_summary_tiles():
    """ADM-006/D5.1: live queue counters for the operational dashboard's opening panel."""
    now = timezone.now()
    return [
        _stale_projects_tile(now),
        _sync_failures_tile(),
        _applications_past_sla_tile(now),
        _open_queues_tile(),
    ]


def _thirty_day_activation() -> int | None:
    organizations = list(
        MinistryOrganization.objects.exclude(provisioned_at__isnull=True).values(
            "id", "provisioned_at"
        )
    )
    if not organizations:
        return None
    activation_events = AuditEvent.objects.filter(action="ministry.activated").values(
        "object_id", "created_at"
    )
    activation_by_organization = {}
    for event in activation_events.order_by("object_id", "created_at"):
        activation_by_organization.setdefault(event["object_id"], event["created_at"])
    activated_in_time = sum(
        1
        for organization in organizations
        if (activation := activation_by_organization.get(str(organization["id"]))) is not None
        and activation <= organization["provisioned_at"] + timedelta(days=30)
    )
    return round(100 * activated_in_time / len(organizations))


def _median_first_response_days() -> float | None:
    response_events = ApplicationEvent.objects.filter(
        event__in=(ApplicationEventType.STATUS_CHANGED, ApplicationEventType.INFO_REQUESTED)
    ).values("application_id", "application__submitted_at", "created_at")
    first_responses = {}
    for event in response_events.order_by("application_id", "created_at"):
        first_responses.setdefault(event["application_id"], event)
    durations = [
        (event["created_at"] - event["application__submitted_at"]).total_seconds() / 86400
        for event in first_responses.values()
        if event["created_at"] >= event["application__submitted_at"]
    ]
    return round(median(durations), 1) if durations else None


def _availability_30_days(now) -> tuple[int | None, str]:
    since = now - timedelta(days=AVAILABILITY_WINDOW_DAYS)
    probes = AuditEvent.objects.filter(
        action=AVAILABILITY_PROBE_ACTION,
        created_at__gte=since,
    )
    total = probes.count()
    if total == 0:
        return None, _("No availability probe data has been recorded in the last 30 days.")
    failures = probes.exclude(result="success").count()
    return round(100 * (total - failures) / total, 2), _("%(count)s incident(s)") % {
        "count": failures
    }


def build_adoption_metrics():
    """ADM-006/D5.1: privacy-safe platform aggregates with no member-level data."""
    now = timezone.now()
    activation = _thirty_day_activation()
    first_response = _median_first_response_days()
    availability, availability_detail = _availability_30_days(now)
    return [
        {
            "id": "ministries_active",
            "label": _("Ministries active"),
            "value": MinistryOrganization.objects.filter(status=OrgStatus.ACTIVE).count(),
            "suffix": "",
            "detail": _("Current active organizations"),
        },
        {
            "id": "open_projects",
            "label": _("Open projects"),
            "value": Project.objects.filter(status=ProjectStatus.OPEN_FOR_CONTRIBUTION).count(),
            "suffix": "",
            "detail": _("Current public contribution listings"),
        },
        {
            "id": "thirty_day_activation",
            "label": _("30-day activation"),
            "value": activation,
            "suffix": "%" if activation is not None else "",
            "detail": _("Provisioned organizations activated within 30 days"),
        },
        {
            "id": "median_first_response",
            "label": _("Median first response"),
            "value": first_response,
            "suffix": _(" d") if first_response is not None else "",
            "detail": _("Application decisions and information requests"),
        },
        {
            "id": "verified_contributions",
            "label": _("Verified contributions"),
            "value": ContributionRecord.objects.filter(status=VerificationStatus.ACCEPTED).count(),
            "suffix": "",
            "detail": _("Accepted contribution records"),
        },
        {
            "id": "availability",
            "label": _("Availability · 30 d"),
            "value": availability,
            "suffix": "%" if availability is not None else "",
            "detail": availability_detail,
        },
    ]


def build_ops_panels():
    """ADM-006/NFR-OBS-01: bounded read-only panels for the Super Admin ops dashboard."""
    return [
        _stale_projects_panel(),
        _aging_cases_panel(),
        _repo_health_panel(),
        _notification_delivery_panel(),
        _recent_audit_failures_panel(),
    ]
