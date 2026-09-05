from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.accounts.models import MemberProfile
from apps.accounts.permissions import is_super_admin, privileged_mfa_required
from apps.contributions.models import ContributionRecord
from apps.recognition.enums import AwardStatus
from apps.recognition.forms import (
    BadgeAwardForm,
    BadgeForm,
    BadgeRevokeForm,
    CorrectionAppealForm,
    CorrectionAppealResolutionForm,
    RecognitionCorrectionForm,
    ScoringPolicyForm,
)
from apps.recognition.models import (
    Badge,
    BadgeAward,
    ContributionScore,
    RecognitionCorrection,
    ScoringPolicy,
)
from apps.recognition.services import (
    RecognitionError,
    activate_policy,
    anomaly_summary,
    appeal_correction,
    apply_correction,
    award_badge,
    create_badge,
    leaderboard,
    opt_out,
    resolve_correction_appeal,
    revoke_badge,
    update_badge,
)


def _require_super_admin(user):
    if not is_super_admin(user):
        raise PermissionDenied


@login_required(login_url=reverse_lazy("accounts:login"))
@require_GET
def my_profile(request):
    """REC-003/REC-004/REC-007: show the signed-in member's private recognition history."""
    scores = ContributionScore.objects.filter(
        contribution__contributor=request.user
    ).select_related("contribution__project", "policy")
    awards = BadgeAward.objects.filter(recipient=request.user).select_related(
        "badge", "contribution__project", "issuer", "revoked_by"
    )
    corrections = (
        RecognitionCorrection.objects.filter(recipient=request.user)
        .select_related("applied_by", "appeal_decided_by")
        .prefetch_related("contributions")
    )
    opt_out = (
        MemberProfile.objects.filter(user=request.user)
        .values_list("leaderboard_opt_out", flat=True)
        .first()
    )
    return render(
        request,
        "recognition/my_profile.html",
        {
            "scores": scores,
            "awards": awards,
            "corrections": corrections,
            "leaderboard_opt_out": bool(opt_out),
        },
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@require_POST
def leaderboard_opt_out(request):
    """REC-004: retain private history while removing the member from public rankings."""
    opt_out(request.user)
    return redirect("recognition:my_profile")


@require_GET
def public_leaderboard(request):
    """D12/REC-003/REC-004: expose rankings only when the public policy is enabled."""
    if not settings.RECOGNITION_ENABLED:
        return render(
            request,
            "recognition/leaderboard.html",
            {"entries": (), "public_leaderboard_available": False},
        )
    entries = (
        leaderboard()
        .values("contribution__contributor__username")
        .annotate(points=Sum("points"))
        .order_by("-points", "contribution__contributor__username")
    )
    return render(
        request,
        "recognition/leaderboard.html",
        {"entries": entries, "public_leaderboard_available": True},
    )


@require_GET
def public_badges(request):
    """A3.7/REC-007: publish active badge definitions and their documented criteria."""
    badges = Badge.objects.filter(is_active=True).order_by("name")
    return render(request, "recognition/public_badges.html", {"badges": badges})


@require_GET
def public_badge_detail(request, slug):
    """A3.7/REC-007: disclose one active badge's current criteria version."""
    badge = get_object_or_404(Badge, slug=slug, is_active=True)
    active_award_count = badge.awards.filter(status=AwardStatus.ACTIVE).count()
    return render(
        request,
        "recognition/public_badge_detail.html",
        {"badge": badge, "active_award_count": active_award_count},
    )


@require_GET
def public_policy(request):
    """A3.7/REC-002: disclose the active scoring policy without exposing admin controls."""
    policy = ScoringPolicy.objects.filter(is_active=True).select_related("approved_by").first()
    return render(request, "recognition/public_policy.html", {"policy": policy})


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_http_methods(["GET", "POST"])
def policy_create(request):
    """REC-002: activate a documented scoring policy through the audited service."""
    _require_super_admin(request.user)
    form = ScoringPolicyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            activate_policy(request.user, **form.cleaned_data)
        except RecognitionError as error:
            form.add_error(None, str(error))
        else:
            return redirect("recognition:policy_create")
    policies = ScoringPolicy.objects.select_related("approved_by")
    return render(
        request,
        "recognition/policy_form.html",
        {"form": form, "policies": policies},
        status=400 if form.errors else 200,
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_GET
def badge_list(request):
    """REC-007: list badge definitions for verified Super Admin administration."""
    _require_super_admin(request.user)
    return render(request, "recognition/badge_list.html", {"badges": Badge.objects.all()})


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_http_methods(["GET", "POST"])
def badge_create(request):
    """REC-007: create a documented badge using the audited recognition service."""
    _require_super_admin(request.user)
    form = BadgeForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            badge = create_badge(request.user, **form.cleaned_data)
        except RecognitionError as error:
            form.add_error(None, str(error))
        else:
            return redirect("recognition:badge_edit", slug=badge.slug)
    return render(
        request, "recognition/badge_form.html", {"form": form}, status=400 if form.errors else 200
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_http_methods(["GET", "POST"])
def badge_edit(request, slug):
    """REC-007: update badge criteria using the audited recognition service."""
    _require_super_admin(request.user)
    badge = get_object_or_404(Badge, slug=slug)
    form = BadgeForm(request.POST or None, request.FILES or None, instance=badge)
    if request.method == "POST" and form.is_valid():
        try:
            update_badge(request.user, badge, **form.cleaned_data)
        except RecognitionError as error:
            form.add_error(None, str(error))
        else:
            return redirect("recognition:badge_edit", slug=badge.slug)
    awards = badge.awards.select_related("badge", "recipient", "issuer", "revoked_by")
    return render(
        request,
        "recognition/badge_form.html",
        {"badge": badge, "form": form, "awards": awards},
        status=400 if form.errors else 200,
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_http_methods(["GET", "POST"])
def badge_award(request, slug):
    """REC-007: award an existing badge to a member with a reasoned audit trail."""
    _require_super_admin(request.user)
    badge = get_object_or_404(Badge, slug=slug)
    form = BadgeAwardForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        recipient = get_object_or_404(get_user_model(), username=form.cleaned_data["username"])
        try:
            award_badge(request.user, recipient, badge, reason=form.cleaned_data["reason"])
        except RecognitionError as error:
            form.add_error(None, str(error))
        else:
            return redirect("recognition:badge_edit", slug=badge.slug)
    return render(
        request,
        "recognition/badge_award_form.html",
        {"badge": badge, "form": form},
        status=400 if form.errors else 200,
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_http_methods(["GET", "POST"])
def award_revoke(request, pk):
    """REC-005/REC-007: revoke a badge award with a reason and audit evidence."""
    _require_super_admin(request.user)
    award = get_object_or_404(
        BadgeAward.objects.select_related("badge", "recipient", "revoked_by"), pk=pk
    )
    form = BadgeRevokeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            revoke_badge(request.user, award, form.cleaned_data["reason"])
        except RecognitionError as error:
            form.add_error(None, str(error))
        else:
            return redirect("recognition:badge_edit", slug=award.badge.slug)
    return render(
        request,
        "recognition/award_revoke_form.html",
        {"award": award, "form": form},
        status=400 if form.errors else 200,
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_GET
def anomaly_review(request):
    """REC-006: read-only review of recognition velocity and duplicate anomalies."""
    _require_super_admin(request.user)
    return render(request, "recognition/anomaly_review.html", anomaly_summary())


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_http_methods(["GET", "POST"])
def correction_create(request):
    """REC-005/ADM-007: a verified Super Admin applies the D4.3 recognition correction."""
    _require_super_admin(request.user)
    form = RecognitionCorrectionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        contributions = list(
            ContributionRecord.objects.filter(pk__in=form.cleaned_data["contribution_ids"])
            .select_related("contributor", "project")
            .order_by("pk")
        )
        try:
            correction = apply_correction(
                request.user,
                contributions=contributions,
                kind=form.cleaned_data["kind"],
                reason=form.cleaned_data["reason"],
                basis=form.cleaned_data["basis"],
                member_note=form.cleaned_data["member_note"],
                adjusted_points=form.cleaned_data["adjusted_points"],
            )
        except RecognitionError as error:
            form.add_error(None, str(error))
        else:
            return redirect("recognition:correction_detail", pk=correction.pk)
    return render(
        request,
        "recognition/correction_form.html",
        {"form": form},
        status=400 if form.errors else 200,
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_http_methods(["GET", "POST"])
def correction_detail(request, pk):
    """ADM-007/REC-005: a Super Admin reviews a correction and resolves its appeal."""
    _require_super_admin(request.user)
    correction = get_object_or_404(
        RecognitionCorrection.objects.select_related(
            "recipient", "applied_by", "appeal_decided_by"
        ).prefetch_related("contributions__project"),
        pk=pk,
    )
    form = CorrectionAppealResolutionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            resolve_correction_appeal(request.user, correction, **form.cleaned_data)
        except RecognitionError as error:
            form.add_error(None, str(error))
        else:
            return redirect("recognition:correction_detail", pk=correction.pk)
    return render(
        request,
        "recognition/correction_detail.html",
        {"correction": correction, "form": form},
        status=400 if form.errors else 200,
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@require_http_methods(["GET", "POST"])
def correction_appeal(request, pk):
    """ADM-007/BR-010: an affected member submits one correction appeal without record leakage."""
    correction = get_object_or_404(
        RecognitionCorrection.objects.select_related("recipient", "applied_by"),
        pk=pk,
        recipient=request.user,
    )
    form = CorrectionAppealForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            appeal_correction(request.user, correction, form.cleaned_data["grounds"])
        except RecognitionError as error:
            form.add_error(None, str(error))
        else:
            return redirect("recognition:my_profile")
    return render(
        request,
        "recognition/correction_appeal.html",
        {"correction": correction, "form": form},
        status=400 if form.errors else 200,
    )
