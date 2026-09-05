from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.accounts.services import mfa_verified
from apps.audit.models import AuditEvent
from apps.contributions.enums import VerificationStatus
from apps.contributions.forms import EvidenceForm
from apps.contributions.models import ContributionRecord
from apps.contributions.services import (
    ContributionServiceError,
    Evidence,
    SubmissionNotEligibleError,
    UnauthorizedRevokerError,
    UnauthorizedVerifierError,
    can_submit_evidence,
    revoke,
    submit_evidence,
    verify,
)
from apps.ministries.enums import ContactVerificationStatus, PublisherStatus
from apps.projects.enums import ProjectStatus
from apps.projects.models import Project, ProjectMaintainer


def _contribution_queryset():
    return ContributionRecord.objects.select_related(
        "project__ministry",
        "contributor",
        "contribution_type",
        "verified_by",
        "secondary_approval_by",
        "revoked_by",
    )


def _can_view_contribution(user, contribution: ContributionRecord) -> bool:
    if not user.is_active:
        return False
    if user.is_superuser or contribution.contributor_id == user.pk:
        return True
    return ProjectMaintainer.objects.filter(
        project_id=contribution.project_id, user_id=user.pk
    ).exists()


def _visible_contribution_or_404(user, contribution_id: int) -> ContributionRecord:
    contribution = get_object_or_404(_contribution_queryset(), pk=contribution_id)
    if not _can_view_contribution(user, contribution):
        raise Http404
    return contribution


def _can_verify(user, contribution: ContributionRecord) -> bool:
    if not user.is_active:
        return False
    if user.is_superuser:
        return mfa_verified(user)
    return ProjectMaintainer.objects.filter(
        project_id=contribution.project_id, user_id=user.pk
    ).exists()


def _can_revoke(user, contribution: ContributionRecord) -> bool:
    return (
        user.is_active
        and user.is_superuser
        and mfa_verified(user)
        and contribution.status == VerificationStatus.ACCEPTED
    )


def _second_approvers(contribution: ContributionRecord, verifier):
    return (
        get_user_model()
        .objects.filter(
            Q(is_superuser=True)
            | Q(
                publisher_assignments__ministry_id=contribution.project.ministry_id,
                publisher_assignments__status=PublisherStatus.ACTIVE,
                publisher_assignments__contact_verification_status=ContactVerificationStatus.VERIFIED,
            )
        )
        .filter(is_active=True)
        .exclude(pk=verifier.pk)
        .distinct()
    )


def _history(contribution: ContributionRecord):
    content_type = ContentType.objects.get_for_model(ContributionRecord)
    return AuditEvent.objects.filter(
        content_type=content_type,
        object_id=str(contribution.pk),
        result="success",
    ).select_related("actor")


def _verification_queue(user):
    if not user.is_active:
        raise PermissionDenied
    records = _contribution_queryset().filter(
        status__in=(VerificationStatus.CANDIDATE, VerificationStatus.PENDING_INFO)
    )
    if user.is_superuser:
        if not mfa_verified(user):
            raise PermissionDenied
        return records
    project_ids = ProjectMaintainer.objects.filter(user=user).values("project_id")
    if not project_ids.exists():
        raise PermissionDenied
    return records.filter(project_id__in=project_ids)


@login_required(login_url=reverse_lazy("accounts:login"))
@require_GET
def verification_queue(request: HttpRequest) -> HttpResponse:
    """C4.1/BR-006: list candidate evidence for authorized reviewers only."""
    return render(
        request,
        "contributions/verification_queue.html",
        {"contributions": _verification_queue(request.user)},
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@csrf_protect
@require_http_methods(["GET", "POST"])
def submit(request: HttpRequest, project_id: int) -> HttpResponse:
    project = get_object_or_404(
        Project.objects.select_related("ministry"),
        pk=project_id,
        status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
    )
    if not can_submit_evidence(request.user, project):
        raise Http404
    if request.method == "GET":
        return render(
            request,
            "contributions/evidence_form.html",
            {"project": project, "form": EvidenceForm()},
        )
    form = EvidenceForm(request.POST)
    if not form.is_valid():
        return render(
            request,
            "contributions/evidence_form.html",
            {"project": project, "form": form},
            status=400,
        )
    try:
        contribution = submit_evidence(
            request.user,
            project,
            Evidence(
                title=form.cleaned_data["title"],
                contribution_type=form.cleaned_data["contribution_type"],
                description=form.cleaned_data["description"],
                evidence_url=form.cleaned_data["evidence_url"],
            ),
        )
    except SubmissionNotEligibleError:
        return render(
            request,
            "contributions/evidence_form.html",
            {
                "project": project,
                "form": form,
                "error": _("This project is not currently accepting direct evidence submissions."),
            },
            status=400,
        )
    except ContributionServiceError:
        return render(
            request,
            "contributions/evidence_form.html",
            {"project": project, "form": form, "error": _("Unable to submit this evidence.")},
            status=400,
        )
    return redirect("contributions:detail", contribution_id=contribution.pk)


@login_required(login_url=reverse_lazy("accounts:login"))
@require_GET
def detail(request: HttpRequest, contribution_id: int) -> HttpResponse:
    contribution = _visible_contribution_or_404(request.user, contribution_id)
    can_verify = _can_verify(request.user, contribution)
    second_approvers = get_user_model().objects.none()
    if can_verify:
        second_approvers = _second_approvers(contribution, request.user)
    return render(
        request,
        "contributions/detail.html",
        {
            "contribution": contribution,
            "can_verify": can_verify and contribution.status != VerificationStatus.REVOKED,
            "can_revoke": _can_revoke(request.user, contribution),
            "decision_choices": [
                (status, VerificationStatus(status).label)
                for status in (
                    VerificationStatus.ACCEPTED,
                    VerificationStatus.REJECTED,
                    VerificationStatus.PENDING_INFO,
                )
            ],
            "second_approvers": second_approvers,
        },
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@require_GET
def history(request: HttpRequest, contribution_id: int) -> HttpResponse:
    contribution = _visible_contribution_or_404(request.user, contribution_id)
    return render(
        request,
        "contributions/history.html",
        {"contribution": contribution, "events": _history(contribution)},
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@csrf_protect
@require_POST
def verify_contribution(request: HttpRequest, contribution_id: int) -> HttpResponse:
    contribution = get_object_or_404(_contribution_queryset(), pk=contribution_id)
    second_approver_id = request.POST.get("second_approval_by", "")
    second_approval_by = None
    if second_approver_id:
        second_approval_by = get_user_model().objects.filter(pk=second_approver_id).first()
    try:
        verify(
            request.user,
            contribution,
            request.POST.get("decision", ""),
            request.POST.get("reason", ""),
            second_approval_by=second_approval_by,
        )
    except (UnauthorizedVerifierError, PermissionDenied) as error:
        raise PermissionDenied from error
    except ContributionServiceError:
        return _detail_error(
            request,
            contribution,
            _("This verification decision cannot be recorded."),
        )
    return redirect("contributions:detail", contribution_id=contribution.pk)


@login_required(login_url=reverse_lazy("accounts:login"))
@csrf_protect
@require_POST
def revoke_contribution(request: HttpRequest, contribution_id: int) -> HttpResponse:
    contribution = get_object_or_404(_contribution_queryset(), pk=contribution_id)
    try:
        revoke(request.user, contribution, request.POST.get("reason", ""))
    except (UnauthorizedRevokerError, PermissionDenied) as error:
        raise PermissionDenied from error
    except ContributionServiceError:
        return _detail_error(request, contribution, _("This contribution cannot be revoked."))
    return redirect("contributions:detail", contribution_id=contribution.pk)


def _detail_error(
    request: HttpRequest, contribution: ContributionRecord, error: str
) -> HttpResponse:
    return render(
        request,
        "contributions/detail.html",
        {
            "contribution": contribution,
            "can_verify": _can_verify(request.user, contribution),
            "can_revoke": _can_revoke(request.user, contribution),
            "decision_choices": [
                (status, VerificationStatus(status).label)
                for status in (
                    VerificationStatus.ACCEPTED,
                    VerificationStatus.REJECTED,
                    VerificationStatus.PENDING_INFO,
                )
            ],
            "second_approvers": _second_approvers(contribution, request.user),
            "error": error,
        },
        status=400,
    )
