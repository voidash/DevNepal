"""AUTH-001/AUTH-002/GIT-002: GitHub connect identity flows."""

import json
import logging
from urllib.parse import parse_qs, urlsplit

import pytest
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core import signing
from django.urls import reverse

from apps.accounts import github
from apps.accounts.models import MemberProfile, UserSession
from apps.accounts.tests.factories import UserFactory
from apps.audit.models import AuditEvent
from apps.github_sync.models import GithubConnection
from apps.github_sync.tests.factories import GithubConnectionFactory

pytestmark = pytest.mark.django_db

CLIENT_ID = "test-github-client-id"
CLIENT_SECRET = "test-github-client-secret"
ACCESS_TOKEN = "gho_in_memory_token_2026"
GITHUB_PROFILE = {"id": 424242, "login": "kathmandu-dev", "email": "unused@example.com"}
VERIFIED_EMAILS = [
    {"email": "shadow@example.com", "primary": False, "verified": True},
    {"email": "primary@example.com", "primary": True, "verified": True},
]
UNVERIFIED_EMAILS = [{"email": "primary@example.com", "primary": True, "verified": False}]
TOKEN_SCOPE = "read:user,user:email"


@pytest.fixture
def oauth(settings):
    settings.GITHUB_CLIENT_ID = CLIENT_ID
    settings.GITHUB_CLIENT_SECRET = CLIENT_SECRET


def patch_github(monkeypatch, *, emails=VERIFIED_EMAILS, profile=GITHUB_PROFILE):
    calls = []

    def fake_exchange(config, code):
        calls.append({"code": code})
        return ACCESS_TOKEN, github.parse_scopes(TOKEN_SCOPE)

    def fake_profile(access_token):
        calls.append({"profile_token": access_token})
        return profile

    def fake_emails(access_token):
        calls.append({"emails_token": access_token})
        return emails

    monkeypatch.setattr(github, "exchange_code", fake_exchange)
    monkeypatch.setattr(github, "fetch_github_user", fake_profile)
    monkeypatch.setattr(github, "fetch_user_emails", fake_emails)
    return calls


def start_and_callback(client, code="good-code"):
    client.post(reverse("accounts:github_connect"))
    state = client.session[github.STATE_SESSION_KEY]
    return client.get(reverse("accounts:github_callback"), {"code": code, "state": state})


@pytest.mark.unit
def test_connect_initiation_redirects_with_signed_state_and_minimal_scope(client, oauth):
    """AUTH-002: connect starts at GitHub with a signed state bound to the session."""
    response = client.post(reverse("accounts:github_connect"))

    assert response.status_code == 302
    parts = urlsplit(response["Location"])
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == github.GITHUB_AUTHORIZE_URL
    query = parse_qs(parts.query)
    assert query["client_id"] == [CLIENT_ID]
    assert query["scope"] == ["read:user user:email"]
    state = client.session[github.STATE_SESSION_KEY]
    assert query["state"] == [state]
    signing.loads(state, max_age=600)
    assert client.get(reverse("accounts:github_connect")).status_code == 405


@pytest.mark.unit
def test_disabled_provider_returns_404_and_hides_the_connect_button(client, settings):
    """AUTH-001: an unconfigured provider is disabled in routes and every surface."""
    settings.GITHUB_CLIENT_ID = ""
    settings.GITHUB_CLIENT_SECRET = ""

    assert client.post(reverse("accounts:github_connect")).status_code == 404
    assert client.get(reverse("accounts:github_callback")).status_code == 404
    login_page = client.get(reverse("accounts:login"))
    assert b"Connect with GitHub account" not in login_page.content
    assert reverse("accounts:github_connect").encode() not in login_page.content

    client.force_login(UserFactory())
    dashboard = client.get(reverse("accounts:dashboard"))
    assert b"Connect with GitHub account" not in dashboard.content


@pytest.mark.unit
def test_install_return_without_state_is_welcomed_and_audited(client, oauth, monkeypatch):
    """GIT-003/GIT-002: a GitHub installation return has no connect state and is not an error."""
    calls = patch_github(monkeypatch)

    response = client.get(
        reverse("accounts:github_callback"),
        {
            "code": "install-code",
            "installation_id": "159188767",
            "setup_action": "install",
        },
    )

    assert response.status_code == 302
    assert response.url == reverse("accounts:dashboard")
    assert calls == []
    assert not GithubConnection.objects.exists()
    assert "_auth_user_id" not in client.session
    assert AuditEvent.objects.filter(
        action="github_app.install_returned",
        after__installation_id="159188767",
    ).exists()


@pytest.mark.unit
def test_state_mismatch_is_rejected_and_audited(client, oauth, monkeypatch):
    """AUTH-002: a callback whose state fails session validation is rejected and audited."""
    calls = patch_github(monkeypatch)

    client.post(reverse("accounts:github_connect"))
    response = client.get(
        reverse("accounts:github_callback"), {"code": "good-code", "state": "forged-state"}
    )

    assert response.status_code == 400
    assert calls == []
    assert not GithubConnection.objects.exists()
    assert "_auth_user_id" not in client.session
    assert AuditEvent.objects.filter(
        action="github_connection.state_mismatch", result="failure"
    ).exists()
    assert not AuditEvent.objects.filter(action="github_connection.connect").exists()


@pytest.mark.unit
def test_callback_links_github_to_the_authenticated_member(client, oauth, monkeypatch):
    """AUTH-002/GIT-002: connecting as a member records consented identity fields only."""
    calls = patch_github(monkeypatch)
    member = UserFactory()
    client.force_login(member)

    response = start_and_callback(client)

    assert response.status_code == 302
    assert response.url == reverse("accounts:dashboard")
    assert calls[0]["code"] == "good-code"
    assert calls[1]["profile_token"] == ACCESS_TOKEN
    assert calls[2]["emails_token"] == ACCESS_TOKEN
    connection = GithubConnection.objects.get(user=member)
    assert connection.github_user_id == 424242
    assert connection.login == "kathmandu-dev"
    assert connection.scopes == ["read:user", "user:email"]
    assert connection.consent_scopes == ["read:user", "user:email"]
    assert connection.consent_recorded_at is not None
    assert connection.revoked_at is None
    assert AuditEvent.objects.filter(
        action="github_connection.connect", actor=member, result="success"
    ).exists()
    assert client.session["_auth_user_id"] == str(member.pk)


@pytest.mark.unit
def test_callback_provisions_and_signs_in_a_new_member_from_verified_email(
    client, oauth, monkeypatch
):
    """AUTH-001/GIT-002: a first-time GitHub identity becomes an account from the verified email."""
    patch_github(monkeypatch)

    response = start_and_callback(client)

    assert response.status_code == 302
    user = get_user_model().objects.get(email="primary@example.com")
    assert user.username == "kathmandu-dev"
    assert not user.has_usable_password()
    assert MemberProfile.objects.filter(user=user).exists()
    assert GithubConnection.objects.get(user=user).github_user_id == 424242
    assert client.session["_auth_user_id"] == str(user.pk)
    assert AuditEvent.objects.filter(
        action="github_connection.connect", actor=user, result="success"
    ).exists()


@pytest.mark.unit
def test_callback_refuses_unverified_email(client, oauth, monkeypatch):
    """GIT-002: account creation never imports an unverified GitHub email."""
    patch_github(monkeypatch, emails=UNVERIFIED_EMAILS)

    response = start_and_callback(client)
    followed = client.get(response.url)

    assert response.status_code == 302
    assert response.url == reverse("accounts:login")
    assert not get_user_model().objects.filter(email="primary@example.com").exists()
    assert not GithubConnection.objects.exists()
    assert AuditEvent.objects.filter(
        action="github_connection.unverified_email", result="failure"
    ).exists()
    assert any(
        "could not be completed" in str(message) for message in get_messages(followed.wsgi_request)
    )


@pytest.mark.unit
def test_existing_connection_signs_the_member_back_in(client, oauth, monkeypatch):
    """AUTH-002: a returning GitHub identity maps onto the existing active connection."""
    patch_github(monkeypatch)
    member = UserFactory()
    connection = GithubConnectionFactory(
        user=member,
        github_user_id=424242,
        login="stale-login",
        scopes=[],
        consent_scopes=[],
    )

    response = start_and_callback(client)
    connection.refresh_from_db()

    assert response.status_code == 302
    assert client.session["_auth_user_id"] == str(member.pk)
    assert get_user_model().objects.count() == 1
    assert connection.login == "kathmandu-dev"
    assert connection.scopes == ["read:user", "user:email"]
    assert connection.consent_recorded_at >= connection.connected_at


@pytest.mark.unit
def test_suspended_member_is_not_signed_in_through_github(client, oauth, monkeypatch):
    """AUTH-009/AUTH-002: a suspended account cannot re-enter through provider login."""
    patch_github(monkeypatch)
    suspended = UserFactory(is_active=False)
    GithubConnectionFactory(user=suspended, github_user_id=424242)

    response = start_and_callback(client)

    assert response.status_code == 302
    assert response.url == reverse("accounts:login")
    assert "_auth_user_id" not in client.session
    assert AuditEvent.objects.filter(
        action="github_connection.login_refused", result="failure"
    ).exists()


@pytest.mark.unit
def test_github_signup_refuses_an_email_already_registered(client, oauth, monkeypatch):
    """AUTH-002: an existing platform email cannot be claimed through provider signup."""
    patch_github(monkeypatch)
    member = UserFactory(email="primary@example.com")

    response = start_and_callback(client)

    assert response.status_code == 302
    assert response.url == reverse("accounts:login")
    assert get_user_model().objects.filter(email="primary@example.com").count() == 1
    assert get_user_model().objects.get(email="primary@example.com") == member
    assert not GithubConnection.objects.exists()
    assert AuditEvent.objects.filter(
        action="github_connection.email_in_use", result="failure"
    ).exists()


@pytest.mark.unit
def test_connect_conflicts_when_the_github_identity_is_owned_elsewhere(client, oauth, monkeypatch):
    """AUTH-006/AUTH-002: a member cannot take over another member's GitHub identity."""
    patch_github(monkeypatch)
    owner = UserFactory()
    GithubConnectionFactory(user=owner, github_user_id=424242)
    member = UserFactory()
    client.force_login(member)

    response = start_and_callback(client)

    assert response.status_code == 302
    assert response.url == reverse("accounts:login")
    assert not GithubConnection.objects.filter(user=member).exists()
    assert GithubConnection.objects.get(user=owner).github_user_id == 424242
    assert AuditEvent.objects.filter(
        action="github_connection.conflict", actor=member, result="failure"
    ).exists()


@pytest.mark.unit
def test_provider_exchange_failure_fails_closed_with_audit(client, oauth, monkeypatch):
    """AUTH-002: token exchange failures redirect to sign-in and audit the failure."""

    def failing_exchange(config, code):
        raise github.GitHubTokenExchangeError("GitHub rejected the authorization code")

    monkeypatch.setattr(github, "exchange_code", failing_exchange)

    response = start_and_callback(client)
    followed = client.get(response.url)

    assert response.status_code == 302
    assert response.url == reverse("accounts:login")
    assert any(
        "could not be completed" in str(message) for message in get_messages(followed.wsgi_request)
    )
    assert AuditEvent.objects.filter(
        action="github_connection.exchange_failed", result="failure"
    ).exists()
    assert not GithubConnection.objects.exists()


@pytest.mark.unit
def test_callback_handles_github_denied_error_without_side_effects(client, oauth, monkeypatch):
    """AUTH-002: an OAuth denial returns to sign-in without contacting GitHub."""
    calls = patch_github(monkeypatch)

    client.post(reverse("accounts:github_connect"))
    state = client.session[github.STATE_SESSION_KEY]
    response = client.get(
        reverse("accounts:github_callback"),
        {"error": "access_denied", "error_description": "nope", "state": state},
    )

    assert response.status_code == 302
    assert response.url == reverse("accounts:login")
    assert calls == []
    assert AuditEvent.objects.filter(action="github_connection.denied", result="failure").exists()


@pytest.mark.unit
def test_the_oauth_token_is_never_persisted_or_logged(client, oauth, monkeypatch, caplog):
    """AUTH-008/GIT-002: the access token stays in memory — never DB, audit, or logs."""
    patch_github(monkeypatch)
    member = UserFactory()
    client.force_login(member)
    caplog.set_level(logging.INFO)

    response = start_and_callback(client)
    stored = []
    for connection in GithubConnection.objects.all():
        stored.extend(
            str(getattr(connection, field.name)) for field in GithubConnection._meta.fields
        )
    for event in AuditEvent.objects.all():
        stored.append(event.action)
        stored.append(json.dumps({"before": event.before, "after": event.after}, default=str))
    for row in UserSession.objects.all():
        stored.extend(str(getattr(row, field.name)) for field in row._meta.fields)

    assert response.status_code == 302
    assert GithubConnection.objects.exists()
    assert all(ACCESS_TOKEN not in part for part in stored)
    assert ACCESS_TOKEN not in caplog.text
    assert ACCESS_TOKEN.encode() not in response.content


@pytest.mark.unit
def test_derived_usernames_are_sanitized_and_collision_safe():
    """GIT-002: usernames derived from GitHub logins are valid and collision-safe."""
    from django.contrib.auth.validators import UnicodeUsernameValidator

    from apps.accounts.services import derive_github_username

    UserFactory(username="kathmandu-dev")

    assert derive_github_username("kathmandu-dev") == "kathmandu-dev-1"
    for login in ("we!rd name#", "", "sītā-dev", "सीता-dev"):
        candidate = derive_github_username(login)
        assert UnicodeUsernameValidator()(candidate) is None
    assert derive_github_username("") == "github-member"
    assert derive_github_username("sītā-dev") == "sītā-dev"


@pytest.mark.unit
def test_member_connect_stays_in_settings_and_off_ministry_login(client, oauth):
    """AUTH-002: legacy GitHub connection stays behind member settings, not ministry login."""
    login_page = client.get(reverse("accounts:login"))
    assert reverse("accounts:github_connect").encode() not in login_page.content

    member = UserFactory()
    client.force_login(member)
    dashboard = client.get(reverse("accounts:dashboard"))
    assert reverse("accounts:github_connect").encode() in dashboard.content
    assert b"Connect with GitHub account" in dashboard.content
