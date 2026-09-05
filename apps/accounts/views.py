import logging
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.contenttypes.models import ContentType
from django.core.paginator import Paginator
from django.db import transaction
from django.http import Http404, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext
from django.views.decorators.http import require_GET, require_http_methods
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.accounts import github as github_oauth
from apps.accounts.forms import (
    LocalAuthenticationForm,
    MemberLinkFormSet,
    MemberProfileForm,
    MemberSignupForm,
    OnboardingProfileForm,
    OnboardingVisibilityForm,
)
from apps.accounts.models import MemberProfile, UserSession
from apps.accounts.permissions import privileged_mfa_required, requires_mfa
from apps.accounts.services import (
    GitHubConnectError,
    complete_github_connect,
    create_member_account,
    discoverable_member_profiles,
    export_profile_data,
    preview_public_profile,
    profile_completeness,
    public_profile_payload,
    record_session,
    request_account_deletion,
    revoke_session,
)
from apps.audit.services import record_audit
from apps.github_sync.models import GithubConnection
from apps.github_sync.views import calendar_context
from apps.taxonomy.models import Skill

logger = logging.getLogger(__name__)

ONBOARDING_MEMBER_SESSION_KEY = "accounts.onboarding_member_id"
ONBOARDING_GITHUB_SESSION_KEY = "accounts.onboarding_github"


class LocalLoginView(LoginView):
    authentication_form = LocalAuthenticationForm
    redirect_authenticated_user = True
    template_name = "accounts/login.html"

    def get_default_redirect_url(self):
        return reverse("accounts:dashboard")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["github_oauth_enabled"] = github_oauth.oauth_config().enabled
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        record_session(self.request, self.request.user)
        if self.request.session.pop(ONBOARDING_MEMBER_SESSION_KEY, None) == self.request.user.pk:
            return redirect("accounts:onboarding_profile")
        return response


class LocalLogoutView(LogoutView):
    def dispatch(self, request, *args, **kwargs):
        revoke_session(request.session.session_key or "")
        return super().dispatch(request, *args, **kwargs)


def _profile_for(user) -> MemberProfile:
    profile, _ = MemberProfile.objects.get_or_create(user=user)
    return profile


@require_http_methods(["GET", "POST"])
def signup(request):
    """AUTH-001: self-service member registration.

    Policy: no auto-login. A fresh member is redirected to sign-in with a success
    message so the first authenticated request is always a deliberate one.
    """
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")
    if request.method == "POST":
        form = MemberSignupForm(request.POST)
        if form.is_valid():
            user = create_member_account(
                username=form.cleaned_data["username"],
                email=form.cleaned_data["email"],
                password=form.cleaned_data["password1"],
            )
            messages.success(
                request,
                gettext("Your DevNepal account is ready. Sign in to continue."),
            )
            request.session[ONBOARDING_MEMBER_SESSION_KEY] = user.pk
            return redirect("accounts:login")
        return render(
            request,
            "accounts/signup.html",
            {"form": form, "github_oauth_enabled": github_oauth.oauth_config().enabled},
            status=400,
        )
    return render(
        request,
        "accounts/signup.html",
        {"form": MemberSignupForm(), "github_oauth_enabled": github_oauth.oauth_config().enabled},
    )


@require_http_methods(["POST"])
def github_connect(request):
    """AUTH-002: begin the GitHub connect/sign-in dance with a signed session state."""
    config = github_oauth.oauth_config()
    if not config.enabled:
        raise Http404("GitHub connect is not enabled")
    if request.POST.get("onboarding") == "1":
        request.session[ONBOARDING_GITHUB_SESSION_KEY] = True
    state = github_oauth.generate_state()
    request.session[github_oauth.STATE_SESSION_KEY] = state
    return redirect(github_oauth.authorize_url(config, state))


@require_GET
def github_callback(request):
    """AUTH-001/AUTH-002/GIT-002: finish GitHub connect; the token never leaves memory."""
    config = github_oauth.oauth_config()
    if not config.enabled:
        raise Http404("GitHub connect is not enabled")
    if request.GET.get("setup_action") == "install":
        record_audit(
            actor=request.user if request.user.is_authenticated else None,
            action="github_app.install_returned",
            after={
                "installation_id": request.GET.get("installation_id", ""),
                "setup_action": "install",
            },
        )
        return redirect("accounts:dashboard")
    if not github_oauth.verify_state(request.GET.get("state"), request.session):
        actor = request.user if request.user.is_authenticated else None
        record_audit(actor=actor, action="github_connection.state_mismatch", result="failure")
        return HttpResponseBadRequest(gettext("Invalid or expired GitHub connect state."))
    if request.GET.get("error") or not request.GET.get("code"):
        _refuse_github_connect(request, "github_connection.denied")
        return redirect("accounts:login")
    try:
        access_token, scopes = github_oauth.exchange_code(config, request.GET["code"])
        profile = github_oauth.fetch_github_user(access_token)
        emails = github_oauth.fetch_user_emails(access_token)
    except GitHubConnectError:
        logger.exception("GitHub OAuth exchange failed")
        _refuse_github_connect(request, "github_connection.exchange_failed")
        return redirect("accounts:login")
    try:
        user = complete_github_connect(
            user=request.user, github_profile=profile, emails=emails, scopes=scopes
        )
    except GitHubConnectError:
        messages.error(request, gettext("GitHub connect could not be completed."))
        return redirect("accounts:login")
    if not request.user.is_authenticated or request.user.pk != user.pk:
        user.backend = "django.contrib.auth.backends.ModelBackend"
        login(request, user)
        record_session(request, user)
    messages.success(request, gettext("Your GitHub account is connected."))
    if request.session.pop(ONBOARDING_GITHUB_SESSION_KEY, False):
        if not _profile_for(user).onboarding_completed:
            return redirect("accounts:onboarding_preview")
    return redirect("accounts:dashboard")


def _refuse_github_connect(request, action: str):
    actor = request.user if request.user.is_authenticated else None
    record_audit(actor=actor, action=action, result="failure")
    messages.error(request, gettext("GitHub connect could not be completed."))


@login_required(login_url=reverse_lazy("accounts:login"))
@require_http_methods(["GET", "POST"])
def onboarding_profile(request):
    """AUTH-001/MEM-002/MEM-004: save the optional profile portion of B1 onboarding."""
    profile = _profile_for(request.user)
    if profile.onboarding_completed:
        return redirect("accounts:dashboard")
    form = OnboardingProfileForm(request.POST or None, instance=profile)
    if request.method == "POST":
        if not form.is_valid():
            return render(request, "accounts/onboarding_profile.html", {"form": form}, status=400)
        with transaction.atomic():
            form.save()
            record_audit(actor=request.user, action="account.onboarding_profile_saved", obj=profile)
        return redirect("accounts:onboarding_visibility")
    return render(request, "accounts/onboarding_profile.html", {"form": form})


@login_required(login_url=reverse_lazy("accounts:login"))
@require_http_methods(["GET", "POST"])
def onboarding_visibility(request):
    """MEM-003/REC-004: persist B1.4 public and member-only visibility controls."""
    profile = _profile_for(request.user)
    if profile.onboarding_completed:
        return redirect("accounts:dashboard")
    form = OnboardingVisibilityForm(request.POST or None, profile=profile)
    if request.method == "POST":
        if not form.is_valid():
            return render(
                request, "accounts/onboarding_visibility.html", {"form": form}, status=400
            )
        with transaction.atomic():
            form.save()
            record_audit(
                actor=request.user, action="account.onboarding_visibility_saved", obj=profile
            )
        return redirect("accounts:onboarding_github")
    return render(request, "accounts/onboarding_visibility.html", {"form": form})


@login_required(login_url=reverse_lazy("accounts:login"))
@require_GET
def onboarding_github(request):
    """AUTH-002/GIT-010: disclose actual OAuth availability before optional connection."""
    profile = _profile_for(request.user)
    if profile.onboarding_completed:
        return redirect("accounts:dashboard")
    connection = GithubConnection.objects.filter(user=request.user, revoked_at__isnull=True).first()
    return render(
        request,
        "accounts/onboarding_github.html",
        {
            "github_oauth_enabled": github_oauth.oauth_config().enabled,
            "github_connection": connection,
        },
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@require_http_methods(["POST"])
def onboarding_github_skip(request):
    """GIT-002: record a real optional-provider skip without manufacturing a connection."""
    profile = _profile_for(request.user)
    if not profile.onboarding_completed:
        with transaction.atomic():
            profile.github_onboarding_skipped = True
            profile.save(update_fields=["github_onboarding_skipped", "updated_at"])
            record_audit(
                actor=request.user, action="account.onboarding_github_skipped", obj=profile
            )
    return redirect("accounts:onboarding_preview")


@login_required(login_url=reverse_lazy("accounts:login"))
@require_GET
def onboarding_preview(request):
    """MEM-008: render the persisted visitor projection before an explicit publish action."""
    profile = _profile_for(request.user)
    if profile.onboarding_completed:
        return redirect("accounts:dashboard")
    return render(
        request,
        "accounts/onboarding_preview.html",
        {"payload": public_profile_payload(profile), "profile": profile},
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@require_http_methods(["POST"])
def onboarding_publish(request):
    """MEM-003/MEM-008: publish only after the member explicitly confirms the projection."""
    profile = _profile_for(request.user)
    if not profile.onboarding_completed:
        with transaction.atomic():
            profile.onboarding_completed = True
            profile.save(update_fields=["onboarding_completed", "updated_at"])
            record_audit(actor=request.user, action="account.onboarding_published", obj=profile)
    messages.success(request, gettext("Your profile setup is published."))
    return redirect("accounts:dashboard")


def public_profile(request, username):
    """MEM-003/MEM-005: render the fail-closed public profile projection only."""
    user = get_object_or_404(get_user_model(), username=username, is_active=True)
    profile = get_object_or_404(MemberProfile.objects.select_related("user"), user=user)
    raw_year = request.GET.get("year")
    year = int(raw_year) if raw_year and raw_year.isdigit() and len(raw_year) == 4 else None
    return render(
        request,
        "accounts/public_profile.html",
        {
            "payload": public_profile_payload(profile),
            "report_target": {
                "content_type": ContentType.objects.get_for_model(user).pk,
                "object_id": user.pk,
            },
            **calendar_context(user, year),
        },
    )


@require_GET
def member_directory(request):
    """MEM-003: browse only active profiles whose owners explicitly opted into discovery."""
    profiles, query, skill_slug = discoverable_member_profiles(
        query=request.GET.get("q", ""), skill_slug=request.GET.get("skill", "")
    )
    filters = {"q": query, "skill": skill_slug}
    return render(
        request,
        "accounts/member_directory.html",
        {
            "members": Paginator(profiles, 24).get_page(request.GET.get("page")),
            "query": query,
            "filters": filters,
            "query_string": urlencode({key: value for key, value in filters.items() if value}),
            "skills": Skill.objects.filter(is_active=True),
        },
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@require_http_methods(["GET", "POST"])
def profile_edit(request):
    """MEM-002/MEM-003/MEM-004/MEM-006: members update their profile, taxonomy skills,
    and allowlisted external links in one transactional save."""
    profile = _profile_for(request.user)
    if request.method == "POST":
        form = MemberProfileForm(request.POST, request.FILES, instance=profile)
        if "links-TOTAL_FORMS" in request.POST:
            link_formset = MemberLinkFormSet(request.POST, instance=request.user, prefix="links")
        else:
            link_formset = MemberLinkFormSet(instance=request.user, prefix="links")
        if form.is_valid() and (not link_formset.is_bound or link_formset.is_valid()):
            with transaction.atomic():
                form.save()
                if link_formset.is_bound:
                    link_formset.save()
            return redirect("accounts:profile_edit")
        return render(
            request,
            "accounts/profile_edit.html",
            {"form": form, "link_formset": link_formset},
            status=400,
        )
    return render(
        request,
        "accounts/profile_edit.html",
        {
            "form": MemberProfileForm(instance=profile),
            "link_formset": MemberLinkFormSet(instance=request.user, prefix="links"),
        },
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@require_http_methods(["POST"])
def profile_preview(request):
    """MEM-008: preview unsaved changes without exposing data beyond public visibility."""
    profile = _profile_for(request.user)
    form = MemberProfileForm(request.POST, request.FILES, instance=profile)
    if not form.is_valid():
        return render(request, "accounts/profile_edit.html", {"form": form}, status=400)
    profile = form.save(commit=False)
    return render(
        request,
        "accounts/profile_preview.html",
        {"payload": preview_public_profile(profile), "completeness": profile_completeness(profile)},
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
def dashboard(request):
    """AUTH-005/AUTH-006: role-aware authenticated landing page behind privileged MFA."""
    connection = GithubConnection.objects.filter(user=request.user, revoked_at__isnull=True).first()
    return render(
        request,
        "accounts/dashboard.html",
        {
            "profile": _profile_for(request.user),
            "requires_mfa": requires_mfa(request.user),
            "github_oauth_enabled": github_oauth.oauth_config().enabled,
            "github_connection": connection,
        },
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@require_http_methods(["GET", "POST"])
def mfa_setup(request):
    """AUTH-005: provision and verify a named user's TOTP device."""
    if not requires_mfa(request.user):
        return redirect("accounts:dashboard")
    error = ""
    config_url = None
    device = TOTPDevice.objects.filter(user=request.user).order_by("id").first()
    if request.method == "POST":
        if request.POST.get("action") == "enroll":
            if device is None:
                device = TOTPDevice.objects.create(user=request.user, name="devnepal")
                config_url = device.config_url
            else:
                error = gettext("Multi-factor authentication is already enrolled.")
        elif device is not None:
            token = request.POST.get("token", "")
            if device.verify_token(token):
                otp_login(request, device)
                return redirect("accounts:dashboard")
            error = gettext("Invalid authentication code. Try again.")
    return render(
        request,
        "accounts/mfa_setup.html",
        {"config_url": config_url, "error": error, "can_enroll": device is None},
    )


@login_required(login_url=reverse_lazy("accounts:login"))
def session_list(request):
    """AUTH-007: render the signed-in member's server-side session ledger."""
    sessions = UserSession.objects.filter(user=request.user).order_by("-last_activity")
    return render(request, "accounts/session_list.html", {"sessions": sessions})


@login_required(login_url=reverse_lazy("accounts:login"))
@require_http_methods(["POST"])
def session_revoke(request, pk):
    """AUTH-007: revoke only a session belonging to the signed-in member."""
    session = get_object_or_404(UserSession, pk=pk, user=request.user, revoked_at__isnull=True)
    session.revoked_at = timezone.now()
    session.save(update_fields=["revoked_at"])
    if session.session_key == request.session.session_key:
        logout(request)
        return redirect("accounts:login")
    return redirect("accounts:session_list")


@login_required(login_url=reverse_lazy("accounts:login"))
@require_http_methods(["GET"])
def privacy_export(request):
    """AUTH-010/AUTH-006: return only the signed-in member's data export."""
    return JsonResponse(export_profile_data(request.user))


@login_required(login_url=reverse_lazy("accounts:login"))
@require_http_methods(["POST"])
def privacy_delete(request):
    """AUTH-010/AUTH-006: process deletion only for the signed-in member."""
    request_account_deletion(request.user)
    logout(request)
    return HttpResponse(status=204)
