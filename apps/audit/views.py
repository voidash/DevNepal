import csv
import re
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse_lazy
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.permissions import is_ministry_publisher, is_super_admin, privileged_mfa_required
from apps.audit.models import AuditEvent
from apps.audit.ops import build_ops_panels
from apps.audit.publisher_audit import (
    ALL_CATEGORIES,
    PUBLISHER_AUDIT_CATEGORIES,
    PublisherAuditExportAuthorizationError,
    PublisherAuditExportPurposeError,
    PublisherAuditExportRateLimitError,
    active_publisher_ministries,
    add_event_presentation,
    export_publisher_audit,
    publisher_audit_events,
)

AUDIT_LOG_PAGE_SIZE = 25
AUDIT_RESULT_FILTERS = ("success", "failure", "denied")
AUDIT_ACTION_PREFIX_PATTERN = re.compile(r"^[a-z0-9_.:-]{1,100}$", re.IGNORECASE)
AUDIT_QUERY_MAX_LENGTH = 100
PUBLISHER_AUDIT_SCOPES = ("mine", "organization")


def _require_super_admin(user):
    if not is_super_admin(user):
        raise PermissionDenied


def _clean_action_prefix(raw):
    prefix = raw.strip()
    return prefix if AUDIT_ACTION_PREFIX_PATTERN.fullmatch(prefix) else ""


def _clean_actor_id(raw):
    try:
        actor_id = int(raw)
    except (TypeError, ValueError):
        return 0
    return actor_id if actor_id > 0 else 0


def _clean_query(raw):
    query = raw.strip()
    return query[:AUDIT_QUERY_MAX_LENGTH] if len(query) <= AUDIT_QUERY_MAX_LENGTH else ""


def _clean_publisher_audit_filter(raw, allowed, default):
    return raw if raw in allowed else default


def _publisher_audit_selection(user, data):
    scope = _clean_publisher_audit_filter(data.get("scope", ""), PUBLISHER_AUDIT_SCOPES, "mine")
    category = _clean_publisher_audit_filter(
        data.get("category", ""), PUBLISHER_AUDIT_CATEGORIES, ALL_CATEGORIES
    )
    result = _clean_publisher_audit_filter(data.get("result", ""), AUDIT_RESULT_FILTERS, "")
    ministries = active_publisher_ministries(user)
    ministry_id = _clean_actor_id(data.get("ministry", ""))
    ministry = ministries.filter(pk=ministry_id).first() if ministry_id else None
    if scope == "organization" and ministry is None:
        scope = "mine"
        ministry_id = 0
    if scope != "organization":
        category = ALL_CATEGORIES
    return scope, category, result, ministries, ministry_id, ministry


def _safe_csv_cell(value):
    rendered = str(value or "")
    return f"'{rendered}" if rendered.startswith(("=", "+", "-", "@")) else rendered


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_GET
def ops_dashboard(request):
    """ADM-006/NFR-OBS-01: read-only operational panels for MFA-verified Super Admins."""
    _require_super_admin(request.user)
    return render(request, "audit/ops_dashboard.html", {"panels": build_ops_panels()})


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_GET
def audit_log(request):
    """ADM-008/SEC-008: MFA-verified Super Admins browse the append-only audit trail read-only."""
    _require_super_admin(request.user)

    action = _clean_action_prefix(request.GET.get("action", ""))
    actor = _clean_actor_id(request.GET.get("actor", ""))
    result = request.GET.get("result", "")
    if result not in AUDIT_RESULT_FILTERS:
        result = ""
    query = _clean_query(request.GET.get("q", ""))

    events = AuditEvent.objects.select_related("actor", "content_type").order_by("-created_at")
    if action:
        events = events.filter(action__istartswith=action)
    if actor:
        events = events.filter(actor_id=actor)
    if result:
        events = events.filter(result=result)
    if query:
        events = events.filter(Q(action__icontains=query) | Q(object_id__icontains=query))

    filters = {"action": action, "actor": str(actor) if actor else "", "result": result, "q": query}
    query_string = urlencode({key: value for key, value in filters.items() if value})
    page = Paginator(events, AUDIT_LOG_PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "audit/audit_log.html",
        {
            "events": page,
            "filters": filters,
            "query_string": query_string,
            "result_choices": AUDIT_RESULT_FILTERS,
        },
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_GET
def my_actions(request):
    """GOV-005/ADM-008: MFA-verified publishers inspect their attributable audit history."""
    if not is_ministry_publisher(request.user):
        raise PermissionDenied

    scope, category, result, ministries, ministry_id, ministry = _publisher_audit_selection(
        request.user, request.GET
    )
    events = publisher_audit_events(
        user=request.user,
        ministry=ministry,
        scope=scope,
        category=category,
    )
    if result:
        events = events.filter(result=result)
    filters = {
        "scope": scope,
        "ministry": str(ministry_id) if ministry_id and scope == "organization" else "",
        "category": category,
        "result": result,
    }
    query_string = urlencode({key: value for key, value in filters.items() if value})
    page = Paginator(events, AUDIT_LOG_PAGE_SIZE).get_page(request.GET.get("page"))
    add_event_presentation(page.object_list)
    return render(
        request,
        "audit/my_actions.html",
        {
            "events": page,
            "filters": filters,
            "ministries": ministries,
            "selected_ministry": ministry,
            "result_choices": AUDIT_RESULT_FILTERS,
            "query_string": query_string,
        },
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_POST
def export_my_actions(request):
    """GOV-005/ADM-005: export the authorized C6.2 ledger as injection-safe CSV."""
    if not is_ministry_publisher(request.user):
        raise PermissionDenied
    scope, category, result, _, _, ministry = _publisher_audit_selection(request.user, request.POST)
    try:
        events = export_publisher_audit(
            user=request.user,
            ministry=ministry,
            scope=scope,
            category=category,
            result=result,
            purpose=request.POST.get("purpose", ""),
        )
    except PublisherAuditExportAuthorizationError as error:
        raise PermissionDenied from error
    except PublisherAuditExportPurposeError as error:
        return HttpResponse(str(error), status=400, content_type="text/plain; charset=utf-8")
    except PublisherAuditExportRateLimitError as error:
        response = HttpResponse(str(error), status=429, content_type="text/plain; charset=utf-8")
        response["Retry-After"] = "3600"
        return response

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="devnepal-publisher-audit.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(["When", "Actor", "Action", "Target", "Basis / reason", "Result"])
    for event in events:
        writer.writerow(
            [
                event.created_at.isoformat(),
                _safe_csv_cell(event.actor.username if event.actor else "Platform"),
                _safe_csv_cell(event.action),
                _safe_csv_cell(event.target_reference),
                _safe_csv_cell(event.basis_reason),
                _safe_csv_cell(event.result),
            ]
        )
    return response
