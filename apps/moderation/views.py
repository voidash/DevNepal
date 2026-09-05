from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.accounts.permissions import is_super_admin, privileged_mfa_required
from apps.moderation.enums import CaseStatus, ReportReason
from apps.moderation.forms import (
    AppealForm,
    AppealResolutionForm,
    CaseDecisionForm,
    CaseExportForm,
    ReportForm,
)
from apps.moderation.models import ModerationCase
from apps.moderation.services import (
    AppealError,
    AppealOwnershipError,
    ExportPurposeError,
    ExportRateLimitError,
    ModerationServiceError,
    appeal,
    assign_case,
    build_community_health_snapshot,
    export_case_record,
    file_report,
    record_decision,
    resolve_appeal,
)

CASE_QUEUE_PAGE_SIZE = 25
CASE_QUEUE_ORDERINGS = {
    "newest": ("-created_at", "-pk"),
    "oldest": ("created_at", "pk"),
    "age": ("created_at", "pk"),
    "status": ("status", "-created_at", "-pk"),
}


def _require_super_admin(user):
    if not is_super_admin(user):
        raise PermissionDenied


def _case_queryset():
    return ModerationCase.objects.select_related(
        "assigned_to",
        "appeal_decided_by",
        "decided_by",
        "report__content_type",
        "report__reporter",
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@csrf_protect
@require_http_methods(["GET", "POST"])
def report_create(request):
    """ADM-003: authenticated members file structured reports."""
    if request.method == "GET":
        initial = {
            key: request.GET.get(key, "")
            for key in ("content_type", "object_id")
            if request.GET.get(key, "")
        }
        return render(request, "moderation/report_form.html", {"form": ReportForm(initial=initial)})
    form = ReportForm(request.POST)
    if form.is_valid():
        try:
            report = file_report(
                request.user,
                form.cleaned_data["target"],
                form.cleaned_data["reason"],
                form.cleaned_data["details"],
                form.cleaned_data["evidence_url"],
            )
        except ModerationServiceError:
            form.add_error(None, _("This report could not be submitted."))
        else:
            return redirect("moderation:report_confirmation", pk=report.case.pk)
    return render(request, "moderation/report_form.html", {"form": form}, status=400)


@login_required(login_url=reverse_lazy("accounts:login"))
@require_GET
def report_confirmation(request, pk):
    """ADM-003: reporters can view the status of their own submitted reports."""
    case = get_object_or_404(_case_queryset(), pk=pk, report__reporter=request.user)
    return render(request, "moderation/report_confirmation.html", {"case": case})


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_GET
def case_queue(request):
    """ADM-002: verified Super Admins access the moderation case queue."""
    _require_super_admin(request.user)
    status = request.GET.get("status", "")
    if status not in CaseStatus.values:
        status = ""

    reason = request.GET.get("reason", "")
    if reason not in ReportReason.values:
        reason = ""

    order = request.GET.get("order", "newest")
    if order not in CASE_QUEUE_ORDERINGS:
        order = "newest"

    cases = _case_queryset()
    if status:
        cases = cases.filter(status=status)
    if reason:
        cases = cases.filter(report__reason=reason)
    filters = {"status": status, "reason": reason, "order": order}
    query_string = urlencode({key: value for key, value in filters.items() if value})
    page = Paginator(cases.order_by(*CASE_QUEUE_ORDERINGS[order]), CASE_QUEUE_PAGE_SIZE).get_page(
        request.GET.get("page")
    )
    return render(
        request,
        "moderation/case_queue.html",
        {
            "cases": page,
            "case_statuses": CaseStatus.choices,
            "filters": filters,
            "query_string": query_string,
            "report_reasons": ReportReason.choices,
        },
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_GET
def community_health(request):
    """ADM-006/SRS 3.2: MFA-verified Super Admins view aggregate community health."""
    _require_super_admin(request.user)
    return render(
        request,
        "moderation/community_health.html",
        {"health": build_community_health_snapshot()},
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_GET
def case_detail(request, pk):
    """ADM-002: verified Super Admins access confidential case details and history."""
    _require_super_admin(request.user)
    case = get_object_or_404(_case_queryset(), pk=pk)
    return render(
        request,
        "moderation/case_detail.html",
        {
            "appeal_form": AppealForm(),
            "case": case,
            "decision_form": CaseDecisionForm(),
            "events": case.events.select_related("actor"),
            "export_form": CaseExportForm(),
            "resolution_form": AppealResolutionForm(),
        },
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@csrf_protect
@require_POST
def case_assign(request, pk):
    """ADM-002: a verified Super Admin assigns a case to themselves."""
    _require_super_admin(request.user)
    case = get_object_or_404(_case_queryset(), pk=pk)
    try:
        assign_case(request.user, case)
    except ModerationServiceError as error:
        return _case_error(request, case, str(error))
    return redirect("moderation:case_detail", pk=case.pk)


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@csrf_protect
@require_POST
def case_decide(request, pk):
    """ADM-004: a verified Super Admin records a structured decision."""
    _require_super_admin(request.user)
    case = get_object_or_404(_case_queryset(), pk=pk)
    form = CaseDecisionForm(request.POST)
    if form.is_valid():
        try:
            record_decision(request.user, case, **form.cleaned_data)
        except ModerationServiceError as error:
            return _case_error(request, case, str(error), decision_form=form)
        return redirect("moderation:case_detail", pk=case.pk)
    return _case_error(request, case, _("Choose a valid action and reason."), decision_form=form)


@login_required(login_url=reverse_lazy("accounts:login"))
@csrf_protect
@require_http_methods(["GET", "POST"])
def appeal_case(request, pk):
    """ADM-007: a reporter appeals their own actioned case."""
    case = get_object_or_404(_case_queryset(), pk=pk)
    if request.method == "GET":
        if case.report.reporter_id != request.user.pk:
            raise PermissionDenied
        return render(request, "moderation/appeal_form.html", {"case": case, "form": AppealForm()})
    form = AppealForm(request.POST)
    if form.is_valid():
        try:
            appeal(request.user, case, form.cleaned_data["grounds"])
        except AppealOwnershipError as error:
            raise PermissionDenied from error
        except AppealError as error:
            return _appeal_error(request, case, form, str(error))
        return redirect("moderation:report_create")
    return _appeal_error(request, case, form, _("Appeal grounds are required."))


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@csrf_protect
@require_POST
def case_export(request, pk):
    """ADM-005/SEC-008: a verified Super Admin exports one case with a declared purpose."""
    _require_super_admin(request.user)
    case = get_object_or_404(_case_queryset(), pk=pk)
    form = CaseExportForm(request.POST)
    if form.is_valid():
        try:
            payload = export_case_record(request.user, case, form.cleaned_data["purpose"])
        except ExportPurposeError as error:
            return _case_error(request, case, str(error), export_form=form)
        except ExportRateLimitError as error:
            return HttpResponse(str(error), status=429, content_type="text/plain")
        response = JsonResponse(payload)
        response["Content-Disposition"] = f'attachment; filename="moderation-case-{case.pk}.json"'
        return response
    return _case_error(
        request,
        case,
        _("A structured export purpose is required."),
        export_form=form,
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@csrf_protect
@require_POST
def appeal_resolve(request, pk):
    """ADM-007: a verified Super Admin resolves a pending appeal."""
    _require_super_admin(request.user)
    case = get_object_or_404(_case_queryset(), pk=pk)
    form = AppealResolutionForm(request.POST)
    if form.is_valid():
        try:
            resolve_appeal(request.user, case, **form.cleaned_data)
        except ModerationServiceError as error:
            return _case_error(request, case, str(error), resolution_form=form)
        return redirect("moderation:case_detail", pk=case.pk)
    return _case_error(
        request,
        case,
        _("Choose a valid appeal outcome and reason."),
        resolution_form=form,
    )


def _case_error(request, case, error, **forms):
    return render(
        request,
        "moderation/case_detail.html",
        {
            "appeal_form": forms.get("appeal_form", AppealForm()),
            "case": case,
            "decision_form": forms.get("decision_form", CaseDecisionForm()),
            "error": error,
            "events": case.events.select_related("actor"),
            "export_form": forms.get("export_form", CaseExportForm()),
            "resolution_form": forms.get("resolution_form", AppealResolutionForm()),
        },
        status=400,
    )


def _appeal_error(request, case, form, error):
    return render(
        request,
        "moderation/appeal_form.html",
        {"case": case, "error": error, "form": form},
        status=400,
    )
