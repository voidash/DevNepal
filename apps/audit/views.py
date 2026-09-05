import re
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render
from django.urls import reverse_lazy
from django.views.decorators.http import require_GET

from apps.accounts.permissions import is_super_admin, privileged_mfa_required
from apps.audit.models import AuditEvent
from apps.audit.ops import build_ops_panels

AUDIT_LOG_PAGE_SIZE = 25
AUDIT_RESULT_FILTERS = ("success", "failure", "denied")
AUDIT_ACTION_PREFIX_PATTERN = re.compile(r"^[a-z0-9_.:-]{1,100}$", re.IGNORECASE)
AUDIT_QUERY_MAX_LENGTH = 100


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
