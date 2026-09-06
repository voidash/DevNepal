from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.accounts.permissions import is_super_admin, privileged_mfa_required
from apps.ministries.enums import PublisherStatus
from apps.ministries.forms import (
    ContactConfirmationForm,
    MinistryActionForm,
    MinistryOnboardingRequestForm,
    OnboardingRequestDeclineForm,
    PublisherActionForm,
    PublisherCreateForm,
)
from apps.ministries.models import (
    MinistryOnboardingRequest,
    MinistryOrganization,
    MinistryPublisher,
)
from apps.ministries.services import (
    MinistryOnboardingRequestError,
    MinistryProvisioningError,
    OfficialContactNotificationError,
    OfficialContactVerificationError,
    PublisherAssignmentError,
    PublisherLifecycleError,
    activate_organization,
    create_publisher,
    decline_onboarding_request,
    log_onboarding_request,
    provision_onboarding_request,
    reissue_official_contact_challenge,
    revoke_organization,
    revoke_publisher,
    suspend_organization,
    suspend_publisher,
    verify_official_contact,
)


def _require_super_admin(user):
    if not is_super_admin(user):
        raise PermissionDenied


def _contact_notification_sender(request):
    def send_contact_notification(*, publisher, token):
        confirmation_path = reverse(
            "ministries:contact_confirmation", kwargs={"publisher_id": publisher.pk}
        )
        confirmation_url = request.build_absolute_uri(
            f"{confirmation_path}?{urlencode({'token': token})}"
        )
        send_mail(
            _("Confirm your official contact email"),
            _("Confirm your official contact email for %(ministry)s by opening this link: %(url)s")
            % {"ministry": publisher.ministry.localized_name, "url": confirmation_url},
            None,
            [publisher.official_email],
            fail_silently=False,
        )

    return send_contact_notification


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_GET
def organization_list(request):
    """AUTH-004/ADM-001: list organizations for verified Super Admin management."""
    _require_super_admin(request.user)
    organizations = MinistryOrganization.objects.prefetch_related("publishers__user")
    return render(request, "ministries/organization_list.html", {"organizations": organizations})


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_http_methods(["GET", "POST"])
def onboarding_request_create(request):
    """AUTH-004/D1.1: log a PMO-verified organization onboarding request."""
    _require_super_admin(request.user)
    form = MinistryOnboardingRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            onboarding_request = log_onboarding_request(request.user, **form.cleaned_data)
        except MinistryOnboardingRequestError as exc:
            form.add_error(None, str(exc))
        else:
            return redirect(
                "ministries:onboarding_request_detail",
                reference=onboarding_request.reference,
            )
    return render(
        request,
        "ministries/onboarding_request_form.html",
        {"form": form},
        status=400 if form.errors else 200,
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_GET
def onboarding_request_detail(request, reference):
    """AUTH-004/D1.1: show the checks and accountable choices for one PMO request."""
    _require_super_admin(request.user)
    onboarding_request = get_object_or_404(
        MinistryOnboardingRequest.objects.select_related("provisioned_organization", "logged_by"),
        reference=reference,
    )
    return render(
        request,
        "ministries/onboarding_request_detail.html",
        {
            "onboarding_request": onboarding_request,
            "decline_form": OnboardingRequestDeclineForm(),
        },
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_POST
def onboarding_request_provision(request, reference):
    """AUTH-004/D1.1/D1.2: move a checked request into the ministry provisioning list."""
    _require_super_admin(request.user)
    onboarding_request = get_object_or_404(MinistryOnboardingRequest, reference=reference)
    try:
        provision_onboarding_request(request.user, onboarding_request)
    except MinistryOnboardingRequestError as exc:
        return render(
            request,
            "ministries/onboarding_request_detail.html",
            {
                "onboarding_request": onboarding_request,
                "decline_form": OnboardingRequestDeclineForm(),
                "action_error": str(exc),
            },
            status=409,
        )
    return redirect("ministries:organization_list")


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_POST
def onboarding_request_decline(request, reference):
    """AUTH-004/SEC-008: decline a logged onboarding request with a durable reason."""
    _require_super_admin(request.user)
    onboarding_request = get_object_or_404(MinistryOnboardingRequest, reference=reference)
    form = OnboardingRequestDeclineForm(request.POST)
    if form.is_valid():
        try:
            decline_onboarding_request(
                request.user,
                onboarding_request,
                reason=form.cleaned_data["reason"],
            )
        except MinistryOnboardingRequestError as exc:
            form.add_error(None, str(exc))
        else:
            return redirect(
                "ministries:onboarding_request_detail",
                reference=onboarding_request.reference,
            )
    return render(
        request,
        "ministries/onboarding_request_detail.html",
        {
            "onboarding_request": onboarding_request,
            "decline_form": form,
        },
        status=400,
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_http_methods(["GET", "POST"])
def organization_create(request):
    """D1.1: retain the legacy route only as an entry point to accountable onboarding."""
    _require_super_admin(request.user)
    return redirect("ministries:onboarding_request_create")


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_GET
def organization_detail(request, slug):
    """AUTH-004: show one organization and its named publisher history to a Super Admin."""
    _require_super_admin(request.user)
    ministry = get_object_or_404(
        MinistryOrganization.objects.select_related("onboarding_request"), slug=slug
    )
    publishers = ministry.publishers.select_related("user").all()
    onboarding_request = getattr(ministry, "onboarding_request", None)
    publisher_initial = {}
    if onboarding_request is not None:
        publisher_initial = {
            "title": onboarding_request.nominated_officer_title,
            "official_email": onboarding_request.official_email,
        }
    return render(
        request,
        "ministries/organization_detail.html",
        {
            "ministry": ministry,
            "publishers": publishers,
            "publisher_form": PublisherCreateForm(initial=publisher_initial),
            "onboarding_request": onboarding_request,
            "ministry_action_form": MinistryActionForm(),
            "publisher_action_form": PublisherActionForm(),
        },
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_POST
def organization_action(request, slug):
    """AUTH-004: apply an audited organization lifecycle transition."""
    _require_super_admin(request.user)
    ministry = get_object_or_404(MinistryOrganization, slug=slug)
    form = MinistryActionForm(request.POST)
    if not form.is_valid():
        return render(request, "ministries/organization_form.html", {"form": form}, status=400)
    try:
        if form.cleaned_data["action"] == MinistryActionForm.ACTIVATE:
            activate_organization(request.user, ministry)
        elif form.cleaned_data["action"] == MinistryActionForm.SUSPEND:
            suspend_organization(request.user, ministry, reason=form.cleaned_data["reason"])
        else:
            revoke_organization(request.user, ministry, reason=form.cleaned_data["reason"])
    except MinistryProvisioningError as exc:
        form.add_error(None, str(exc))
        return render(request, "ministries/organization_form.html", {"form": form}, status=409)
    return redirect("ministries:organization_detail", slug=ministry.slug)


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_POST
def publisher_create(request, slug):
    """AUTH-004/AUTH-005: grant a named publisher and send its official-contact challenge."""
    _require_super_admin(request.user)
    ministry = get_object_or_404(MinistryOrganization, slug=slug)
    form = PublisherCreateForm(request.POST)
    if form.is_valid():
        try:
            create_publisher(
                request.user,
                ministry=ministry,
                notification_sender=_contact_notification_sender(request),
                **form.cleaned_data,
            )
        except (
            OfficialContactNotificationError,
            OfficialContactVerificationError,
            PublisherAssignmentError,
        ) as exc:
            form.add_error(None, str(exc))
        else:
            return redirect("ministries:organization_detail", slug=ministry.slug)
    return render(
        request,
        "ministries/organization_detail.html",
        {
            "ministry": ministry,
            "publishers": ministry.publishers.select_related("user"),
            "publisher_form": form,
        },
        status=400,
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_POST
def publisher_action(request, publisher_id):
    """AUTH-004/AUTH-009: suspend or revoke one named publisher through audited services."""
    _require_super_admin(request.user)
    publisher = get_object_or_404(
        MinistryPublisher.objects.select_related("ministry"), pk=publisher_id
    )
    form = PublisherActionForm(request.POST)
    if not form.is_valid():
        return redirect("ministries:organization_detail", slug=publisher.ministry.slug)
    try:
        if form.cleaned_data["action"] == PublisherActionForm.SUSPEND:
            suspend_publisher(request.user, publisher, reason=form.cleaned_data["reason"])
        else:
            revoke_publisher(request.user, publisher, reason=form.cleaned_data["reason"])
    except (MinistryProvisioningError, PublisherLifecycleError):
        return redirect("ministries:organization_detail", slug=publisher.ministry.slug)
    return redirect("ministries:organization_detail", slug=publisher.ministry.slug)


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_http_methods(["GET", "POST"])
def contact_confirmation(request, publisher_id):
    """AUTH-005/D3: require the assigned officer to CSRF-confirm their emailed token."""
    publisher = get_object_or_404(
        MinistryPublisher,
        pk=publisher_id,
        user=request.user,
        status=PublisherStatus.ACTIVE,
    )
    form = ContactConfirmationForm(request.POST or request.GET or None)
    if request.method == "POST" and form.is_valid():
        try:
            verify_official_contact(publisher, form.cleaned_data["token"])
        except OfficialContactVerificationError as exc:
            form.add_error(None, str(exc))
        else:
            return redirect("accounts:dashboard")
    return render(
        request,
        "ministries/contact_confirmation.html",
        {"publisher": publisher, "form": form},
        status=400 if request.method == "POST" and form.errors else 200,
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_POST
def contact_reissue(request, publisher_id):
    """AUTH-005/D3: resend an active officer's unconsumed contact confirmation link."""
    publisher = get_object_or_404(MinistryPublisher, pk=publisher_id, user=request.user)
    try:
        reissue_official_contact_challenge(
            request.user,
            publisher,
            notification_sender=_contact_notification_sender(request),
        )
    except (OfficialContactNotificationError, OfficialContactVerificationError):
        return redirect("accounts:dashboard")
    return redirect("accounts:dashboard")
