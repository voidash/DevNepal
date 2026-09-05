import pytest
from django.http import HttpResponse
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.accounts.rate_limits import (
    GITHUB_CALLBACK_LIMIT,
    GITHUB_CONNECT_LIMIT,
    LOGIN_ATTEMPT_LIMIT,
    MFA_VERIFICATION_LIMIT,
    rate_limit_key,
)
from apps.accounts.tests.factories import UserFactory
from apps.audit.models import AuditEvent
from apps.ministries.tests.factories import MinistryPublisherFactory

pytestmark = pytest.mark.django_db


@pytest.mark.unit
def test_local_login_throttles_failed_attempts_and_audits_the_first_denial(client):
    """SEC-006: local password attempts are bounded without storing raw identifiers."""
    user = UserFactory(username="rate-limited-member")
    user.set_password("correct-password-2026")
    user.save(update_fields=["password"])
    client.defaults["REMOTE_ADDR"] = "198.51.100.41"

    for _ in range(LOGIN_ATTEMPT_LIMIT):
        response = client.post(
            reverse("accounts:login"),
            {"username": user.username, "password": "wrong-password"},
        )
        assert response.status_code == 200

    blocked = client.post(
        reverse("accounts:login"),
        {"username": user.username, "password": "wrong-password"},
    )

    assert blocked.status_code == 429
    assert int(blocked["Retry-After"]) > 0
    assert AuditEvent.objects.filter(
        action="auth.login.rate_limited", result="failure", actor__isnull=True
    ).exists()
    client_key = rate_limit_key("login", "ip:198.51.100.41")
    principal_key = rate_limit_key("login", f"principal:{user.username}")
    assert "198.51.100.41" not in client_key
    assert user.username not in principal_key


@pytest.mark.unit
def test_successful_login_does_not_consume_or_reset_the_shared_ip_budget(client):
    """SEC-006: another account's success cannot reset a victim's IP throttle."""
    target = UserFactory(username="rate-limit-target")
    target.set_password("target-password-2026")
    target.save(update_fields=["password"])
    helper = UserFactory(username="rate-limit-helper")
    helper.set_password("helper-password-2026")
    helper.save(update_fields=["password"])
    client.defaults["REMOTE_ADDR"] = "198.51.100.42"

    for _ in range(LOGIN_ATTEMPT_LIMIT - 1):
        assert (
            client.post(
                reverse("accounts:login"),
                {"username": target.username, "password": "wrong-password"},
            ).status_code
            == 200
        )

    assert (
        client.post(
            reverse("accounts:login"),
            {"username": helper.username, "password": "helper-password-2026"},
        ).status_code
        == 302
    )
    client.logout()

    assert (
        client.post(
            reverse("accounts:login"),
            {"username": target.username, "password": "wrong-password"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            reverse("accounts:login"),
            {"username": target.username, "password": "wrong-password"},
        ).status_code
        == 429
    )


@pytest.mark.unit
def test_login_fails_closed_when_the_rate_limit_cache_is_unavailable(client, caplog, monkeypatch):
    """SEC-006: authentication denies requests when the throttle backend cannot be read."""
    user = UserFactory(username="rate-limit-cache-failure")
    user.set_password("correct-password-2026")
    user.save(update_fields=["password"])

    def unavailable(*args, **kwargs):
        raise RuntimeError("cache backend unavailable")

    monkeypatch.setattr("apps.accounts.rate_limits.cache.get", unavailable)

    response = client.post(
        reverse("accounts:login"),
        {"username": user.username, "password": "correct-password-2026"},
    )

    assert response.status_code == 429
    assert int(response["Retry-After"]) == 900
    assert "Authentication rate-limit cache access failed for surface=login" in caplog.text


@pytest.mark.unit
def test_mfa_verification_throttles_and_audits_the_authenticated_actor(client, monkeypatch):
    """SEC-006: invalid MFA verification submissions receive a bounded 429 response."""
    publisher = UserFactory()
    MinistryPublisherFactory(user=publisher)
    TOTPDevice.objects.create(user=publisher, name="devnepal")
    client.force_login(publisher)
    client.defaults["REMOTE_ADDR"] = "198.51.100.43"
    monkeypatch.setattr("apps.accounts.views.render", lambda *args, **kwargs: HttpResponse())

    for _ in range(MFA_VERIFICATION_LIMIT):
        response = client.post(reverse("accounts:mfa_setup"), {"token": "000000"})
        assert response.status_code == 200

    blocked = client.post(reverse("accounts:mfa_setup"), {"token": "000000"})

    assert blocked.status_code == 429
    assert int(blocked["Retry-After"]) > 0
    assert AuditEvent.objects.filter(
        action="auth.mfa_verification.rate_limited", actor=publisher, result="failure"
    ).exists()


@pytest.fixture
def oauth(settings):
    settings.GITHUB_CLIENT_ID = "test-github-client-id"
    settings.GITHUB_CLIENT_SECRET = "test-github-client-secret"


@pytest.mark.unit
def test_github_connect_throttles_oauth_entry_requests(client, oauth):
    """SEC-006: GitHub OAuth initiation is bounded before authorization redirects."""
    client.defaults["REMOTE_ADDR"] = "198.51.100.44"

    for _ in range(GITHUB_CONNECT_LIMIT):
        assert client.post(reverse("accounts:github_connect")).status_code == 302

    blocked = client.post(reverse("accounts:github_connect"))

    assert blocked.status_code == 429
    assert int(blocked["Retry-After"]) > 0
    assert AuditEvent.objects.filter(
        action="github_connection.connect.rate_limited", result="failure"
    ).exists()


@pytest.mark.unit
def test_github_callback_throttles_invalid_callback_floods(client, oauth):
    """SEC-006: GitHub callback floods are rejected before OAuth token exchange."""
    client.defaults["REMOTE_ADDR"] = "198.51.100.45"

    for _ in range(GITHUB_CALLBACK_LIMIT):
        response = client.get(reverse("accounts:github_callback"), {"state": "invalid"})
        assert response.status_code == 400

    blocked = client.get(reverse("accounts:github_callback"), {"state": "invalid"})

    assert blocked.status_code == 429
    assert int(blocked["Retry-After"]) > 0
    assert AuditEvent.objects.filter(
        action="github_connection.callback.rate_limited", result="failure"
    ).exists()
