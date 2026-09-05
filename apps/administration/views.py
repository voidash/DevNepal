from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.translation import gettext
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.accounts.models import User
from apps.accounts.permissions import is_super_admin, privileged_mfa_required
from apps.administration import console as console_data
from apps.administration import services
from apps.administration.enums import ChangeStatus
from apps.administration.forms import (
    FeatureFlagChangeForm,
    FeatureFlagForm,
    SuperAdminGrantForm,
    SuperAdminRevokeForm,
)
from apps.administration.models import FeatureFlag, FeatureFlagChange, SuperAdminGrant

CHANGE_LOG_LIMIT = 20


def _require_super_admin(user):
    if not is_super_admin(user):
        raise PermissionDenied


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_GET
def console(request):
    """ADM-001/ADM-002/ADM-006: single Super Admin entry point to every privileged surface."""
    _require_super_admin(request.user)
    queues = console_data.build_work_queues()
    return render(
        request,
        "administration/console.html",
        {
            "queues": queues,
            "catalogue": console_data.build_catalogue_entries(),
            "oversight": console_data.build_oversight_entries(),
            "outstanding": sum(queue["count"] for queue in queues),
            "breached": sum(queue["breached"] for queue in queues),
        },
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_http_methods(["GET", "POST"])
def feature_flags(request):
    """ADM-001/D5.7: scoped, owned, reasoned switches with a four-eyes path."""
    _require_super_admin(request.user)
    form = FeatureFlagForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            services.create_feature_flag(request.user, **form.cleaned_data)
            messages.success(request, gettext("Switch registered and left switched off."))
            return redirect("administration:feature_flags")
        messages.error(request, gettext("The switch could not be registered."))
    return render(
        request,
        "administration/feature_flags.html",
        {
            "flags": FeatureFlag.objects.select_related("updated_by"),
            "pending": services.pending_changes(),
            "change_log": FeatureFlagChange.objects.filter(
                status=ChangeStatus.APPLIED
            ).select_related("flag", "proposed_by", "approved_by")[:CHANGE_LOG_LIMIT],
            "form": form,
            "change_form": FeatureFlagChangeForm(),
        },
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_POST
def feature_flag_change(request, key):
    """D5.7/ADM-008: propose or apply a switch change, always with a recorded reason."""
    _require_super_admin(request.user)
    flag = get_object_or_404(FeatureFlag, key=key)
    form = FeatureFlagChangeForm(request.POST)
    if not form.is_valid():
        messages.error(request, gettext("A change to a switch must record a reason."))
        return redirect("administration:feature_flags")

    change = services.request_feature_flag_change(
        request.user,
        flag,
        is_enabled=not flag.is_enabled,
        reason=form.cleaned_data["reason"],
    )
    if change.status == ChangeStatus.PENDING:
        messages.success(
            request,
            gettext("%(label)s is proposed and waiting for a second Super Admin to confirm it.")
            % {"label": flag.label},
        )
    else:
        messages.success(
            request,
            gettext("%(label)s is now on.") % {"label": flag.label}
            if change.to_enabled
            else gettext("%(label)s is now off.") % {"label": flag.label},
        )
    return redirect("administration:feature_flags")


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_POST
def feature_flag_approve(request, change_id):
    """D5.7: a different Super Admin confirms a member-impacting change."""
    _require_super_admin(request.user)
    change = get_object_or_404(FeatureFlagChange, pk=change_id)
    try:
        services.approve_feature_flag_change(request.user, change)
    except services.SelfApprovalError:
        messages.error(
            request,
            gettext(
                "A change must be confirmed by a Super Admin other than the one who proposed it."
            ),
        )
    except services.ChangeNotPendingError:
        messages.error(request, gettext("That change has already been decided."))
    else:
        messages.success(
            request,
            gettext("%(label)s was confirmed and applied.") % {"label": change.flag.label},
        )
    return redirect("administration:feature_flags")


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_http_methods(["GET", "POST"])
def privileged_access(request):
    """AUTH-003/AUTH-007/D5.8: who holds Super Admin, how it was granted, and their sessions."""
    _require_super_admin(request.user)
    form = SuperAdminGrantForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            _propose_grant(request, form)
        else:
            messages.error(request, gettext("A grant needs a named account and a reason."))
        return redirect("administration:privileged_access")
    return render(
        request,
        "administration/privileged_access.html",
        {
            "roster": services.super_admin_roster(),
            "pending_grants": services.pending_grants(),
            "history": SuperAdminGrant.objects.filter(status=ChangeStatus.APPLIED).select_related(
                "subject", "proposed_by", "approved_by"
            )[:CHANGE_LOG_LIMIT],
            "form": form,
        },
    )


def _propose_grant(request, form):
    subject = User.objects.filter(username=form.cleaned_data["username"]).first()
    if subject is None:
        messages.error(request, gettext("No account matches that username."))
        return
    try:
        services.propose_super_admin_grant(
            request.user, subject, reason=form.cleaned_data["reason"]
        )
    except services.RedundantGrantError:
        messages.error(request, gettext("That account already holds Super Admin."))
    else:
        messages.success(
            request,
            gettext("Proposed. A second Super Admin must confirm within 24 hours or it lapses."),
        )


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_POST
def super_admin_grant_confirm(request, grant_id):
    """AUTH-003/D5.8: a different Super Admin confirms a grant inside its window."""
    _require_super_admin(request.user)
    grant = get_object_or_404(SuperAdminGrant, pk=grant_id)
    try:
        services.confirm_super_admin_grant(request.user, grant)
    except services.SelfApprovalError:
        messages.error(
            request,
            gettext(
                "A grant must be confirmed by a Super Admin other than the one who proposed it."
            ),
        )
    except services.GrantExpiredError:
        messages.error(request, gettext("That grant lapsed: it was not confirmed within 24 hours."))
    except services.ChangeNotPendingError:
        messages.error(request, gettext("That grant has already been decided."))
    else:
        messages.success(
            request,
            gettext("%(name)s now holds Super Admin.") % {"name": grant.subject.username},
        )
    return redirect("administration:privileged_access")


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_POST
def super_admin_revoke(request, username):
    """AUTH-003/D5.8: revoke Super Admin immediately and end that person's sessions."""
    _require_super_admin(request.user)
    subject = get_object_or_404(User, username=username)
    form = SuperAdminRevokeForm(request.POST)
    if not form.is_valid():
        messages.error(request, gettext("Revoking Super Admin requires a reason."))
        return redirect("administration:privileged_access")
    try:
        services.revoke_super_admin(request.user, subject, reason=form.cleaned_data["reason"])
    except services.LastSuperAdminError:
        messages.error(request, gettext("The platform must keep at least one Super Admin."))
    except services.RedundantGrantError:
        messages.error(request, gettext("That account does not hold Super Admin."))
    else:
        messages.success(
            request,
            gettext("Super Admin revoked for %(name)s; their sessions have ended.")
            % {"name": subject.username},
        )
    return redirect("administration:privileged_access")
