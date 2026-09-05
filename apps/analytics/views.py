import logging
from datetime import date

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET

from apps.accounts.permissions import privileged_mfa_required
from apps.analytics.enums import EventName
from apps.analytics.services import (
    AnalyticsAuthorizationError,
    AnalyticsReportPeriodError,
    authorize_ministry_analytics,
    monthly_ministry_aggregate,
    monthly_public_report,
)
from apps.ministries.models import MinistryOrganization
from apps.projects.models import Project

logger = logging.getLogger(__name__)

EVENT_LABELS = {
    EventName.PROJECT_VIEWED: _("Project views"),
    EventName.PROJECT_APPLIED: _("Project applications"),
    EventName.CONTRIBUTION_ACCEPTED: _("Accepted contributions"),
}


def _requested_month(raw_value: str | None) -> date:
    if not raw_value:
        return timezone.localdate().replace(day=1)
    try:
        requested = date.fromisoformat(raw_value)
    except (TypeError, ValueError) as exc:
        raise AnalyticsReportPeriodError("month must use YYYY-MM format") from exc
    if requested.day != 1:
        raise AnalyticsReportPeriodError("month must use the first day of a calendar month")
    return requested


def _report_period(request: HttpRequest) -> date:
    raw_month = request.GET.get("month")
    if raw_month and len(raw_month) != 7:
        raise AnalyticsReportPeriodError("month must use YYYY-MM format")
    return _requested_month(f"{raw_month}-01" if raw_month else None)


def _event_rows(event_counts) -> list[dict]:
    return [
        {"label": EVENT_LABELS[event_name], "count": count}
        for event_name, count in sorted(event_counts.items(), key=lambda item: item[0].value)
    ]


@require_GET
def public_monthly_report(request: HttpRequest) -> HttpResponse:
    """ANL-003: render a public report containing only suppressed aggregate analytics."""
    try:
        report = monthly_public_report(month=_report_period(request))
    except AnalyticsReportPeriodError:
        logger.warning("Invalid public analytics report period")
        return HttpResponseBadRequest(_("Enter a month in YYYY-MM format."))
    return render(
        request,
        "analytics/public_monthly_report.html",
        {"report": report, "event_rows": _event_rows(report.aggregate.event_counts)},
    )


@require_GET
def public_monthly_report_export(request: HttpRequest) -> JsonResponse:
    """ANL-004: export self-describing public aggregates without internal group identifiers."""
    try:
        report = monthly_public_report(month=_report_period(request))
    except AnalyticsReportPeriodError:
        logger.warning("Invalid public analytics export period")
        return JsonResponse({"detail": _("Enter a month in YYYY-MM format.")}, status=400)
    return JsonResponse(report.export_payload())


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_GET
def ministry_dashboard(request: HttpRequest, ministry_id: int) -> HttpResponse:
    """ANL-002: show an MFA-verified publisher their own ministry's monthly aggregates."""
    ministry = get_object_or_404(MinistryOrganization, pk=ministry_id)
    try:
        authorize_ministry_analytics(request.user, ministry)
        month = _report_period(request)
    except AnalyticsAuthorizationError:
        logger.warning(
            "Denied ministry analytics dashboard; actor_id=%s ministry_id=%s",
            request.user.pk,
            ministry_id,
        )
        return HttpResponse(status=403)
    except AnalyticsReportPeriodError:
        logger.warning("Invalid ministry analytics report period; ministry_id=%s", ministry_id)
        return HttpResponseBadRequest(_("Enter a month in YYYY-MM format."))
    aggregate = monthly_ministry_aggregate(ministry, month=month)
    project_names = dict(
        Project.objects.filter(ministry=ministry, pk__in=aggregate.project_counts)
        .values_list("pk", "title_en")
        .order_by("title_en")
    )
    project_rows = [
        {"name": project_names[project_id], "count": count}
        for project_id, count in sorted(
            aggregate.project_counts.items(), key=lambda item: project_names[item[0]].casefold()
        )
        if project_id in project_names
    ]
    return render(
        request,
        "analytics/ministry_dashboard.html",
        {
            "aggregate": aggregate,
            "event_rows": _event_rows(aggregate.event_counts),
            "ministry": ministry,
            "project_rows": project_rows,
            "report_month": month,
        },
    )
