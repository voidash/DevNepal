from datetime import timedelta

from django.db.models import Count
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.audit.models import AuditEvent
from apps.github_sync.enums import ProcessingState, SyncState
from apps.github_sync.models import ProviderEvent, RepositoryConnection
from apps.moderation.enums import CaseStatus
from apps.moderation.models import ModerationCase
from apps.notifications.enums import DeliveryStatus
from apps.notifications.models import Notification
from apps.projects.enums import ProjectStatus
from apps.projects.models import Project

PANEL_ROW_LIMIT = 5
PANEL_FETCH_LIMIT = PANEL_ROW_LIMIT + 1
AGING_CASE_DAYS = 5
AUDIT_WINDOW_HOURS = 24
STATE_CLASSES = {"ok": "", "attention": "is-attention", "danger": "is-danger"}


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


def build_ops_panels():
    """ADM-006/NFR-OBS-01: bounded read-only panels for the Super Admin ops dashboard."""
    return [
        _stale_projects_panel(),
        _aging_cases_panel(),
        _repo_health_panel(),
        _notification_delivery_panel(),
        _recent_audit_failures_panel(),
    ]
