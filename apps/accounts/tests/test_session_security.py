import pytest
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import UserFactory, UserSessionFactory

pytestmark = pytest.mark.django_db


@pytest.mark.integration
def test_sec004_session_cookie_is_httponly_and_samesite(client):
    """SEC-004-U1: the session cookie is HttpOnly and SameSite protected."""
    assert settings.SESSION_COOKIE_HTTPONLY is True
    assert settings.SESSION_COOKIE_SAMESITE == "Lax"

    member = UserFactory(username="cookie-member")
    member.set_password("correct-horse-battery-staple")
    member.save()

    response = client.post(
        reverse("accounts:login"),
        {"username": member.username, "password": "correct-horse-battery-staple"},
    )

    assert response.status_code == 302
    cookie = client.cookies[settings.SESSION_COOKIE_NAME]
    assert cookie["httponly"]


@pytest.mark.integration
def test_sec004_authenticated_login_ignores_offsite_next_parameter(client):
    """SEC-004-U2: an offsite next parameter can never drive the redirect target."""
    member = UserFactory(username="redirect-member")
    client.force_login(member)

    response = client.get(reverse("accounts:login"), {"next": "https://evil.example/steal"})

    assert response.status_code == 302
    assert "evil.example" not in response.url


@pytest.mark.integration
def test_sec004_state_changing_post_without_csrf_token_is_rejected(client):
    """SEC-004-U4: CSRF middleware rejects POSTs lacking a CSRF token."""
    csrf_client = client
    csrf_client.force_login(UserFactory(username="csrf-member"))
    enforced = csrf_client.__class__(enforce_csrf_checks=True)
    enforced.cookies.update(csrf_client.cookies)

    response = enforced.post(reverse("notifications:read_all"))

    assert response.status_code == 403


@pytest.mark.integration
def test_srs315_revoked_session_is_logged_out_on_next_request(client):
    """SRS:315/SEC-004: a revoked session row forces logout and redirects to login."""
    member = UserFactory(username="revoked-member")
    client.force_login(member)
    UserSessionFactory(
        user=member,
        session_key=client.session.session_key,
        revoked_at=timezone.now(),
    )

    response = client.get(reverse("accounts:dashboard"))

    assert response.status_code == 302
    assert reverse("accounts:login") in response.url
