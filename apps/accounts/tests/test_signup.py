"""AUTH-001: member self-service signup identity flows."""

import unicodedata

import pytest
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.urls import reverse

from apps.accounts.models import MemberProfile
from apps.accounts.tests.factories import UserFactory
from apps.audit.models import AuditEvent

pytestmark = pytest.mark.django_db

SIGNUP_PAYLOAD = {
    "username": "new-member",
    "email": "new.member@example.com",
    "password1": "glacier-lantern-2026",
    "password2": "glacier-lantern-2026",
}


@pytest.mark.unit
def test_signup_renders_accessible_labelled_fields(client):
    """AUTH-001: the create-account form exposes labelled, autocompleted fields."""
    response = client.get(reverse("accounts:signup"))
    content = response.content.decode()

    assert response.status_code == 200
    assert '<label for="id_username">' in content
    assert '<label for="id_email">' in content
    assert '<label for="id_password1">' in content
    assert '<label for="id_password2">' in content
    assert 'autocomplete="username"' in content
    assert 'autocomplete="email"' in content
    assert 'autocomplete="new-password"' in content
    assert reverse("accounts:login") in content


@pytest.mark.unit
def test_signup_creates_member_and_profile_then_requires_sign_in(client):
    """AUTH-001: signup provisions identity and profile without auto-login."""
    response = client.post(reverse("accounts:signup"), SIGNUP_PAYLOAD)

    user = get_user_model().objects.get(username="new-member")
    assert response.status_code == 302
    assert response.url == reverse("accounts:login")
    assert user.email == "new.member@example.com"
    assert MemberProfile.objects.filter(user=user).exists()
    assert AuditEvent.objects.filter(action="account.created", actor=user).exists()
    assert "_auth_user_id" not in client.session

    page = client.get(response.url)
    assert any("ready" in str(message) for message in get_messages(page.wsgi_request))

    signed_in = client.post(
        reverse("accounts:login"),
        {"username": "new-member", "password": "glacier-lantern-2026"},
    )
    assert signed_in.status_code == 302


@pytest.mark.unit
def test_signup_normalizes_decomposed_unicode_to_nfc(client):
    """AUTH-001/DSC-003: submitted usernames are composed to NFC before validation."""
    payload = SIGNUP_PAYLOAD | {
        "username": unicodedata.normalize("NFD", "devané"),
        "email": "devane@example.com",
    }

    response = client.post(reverse("accounts:signup"), payload)

    assert response.status_code == 302
    stored = get_user_model().objects.get(email="devane@example.com")
    assert stored.username == unicodedata.normalize("NFC", "devané")


@pytest.mark.unit
def test_signup_rejects_an_email_already_registered(client):
    """AUTH-001: a second account cannot claim an email that is already registered."""
    UserFactory(email="taken@example.com")

    response = client.post(
        reverse("accounts:signup"), SIGNUP_PAYLOAD | {"email": "taken@example.com"}
    )

    assert response.status_code == 400
    assert get_user_model().objects.filter(email="taken@example.com").count() == 1
    assert not get_user_model().objects.filter(username="new-member").exists()
    assert not MemberProfile.objects.exists()


@pytest.mark.unit
def test_signup_validates_password_confirmation(client):
    """AUTH-001: mismatched password confirmation re-renders errors and creates nothing."""
    response = client.post(reverse("accounts:signup"), SIGNUP_PAYLOAD | {"password2": "different"})

    assert response.status_code == 400
    assert response.context["form"].errors
    assert not get_user_model().objects.filter(username="new-member").exists()


@pytest.mark.unit
def test_authenticated_members_are_redirected_away_from_signup(client):
    """AUTH-001: signup is a pre-authentication surface only."""
    client.force_login(UserFactory())

    response = client.get(reverse("accounts:signup"))

    assert response.status_code == 302
    assert response.url == reverse("accounts:dashboard")


@pytest.mark.unit
def test_login_page_does_not_offer_contributor_account_creation(client):
    """AUTH-001: ministry sign-in does not lead visitors into a legacy member flow."""
    response = client.get(reverse("accounts:login"))

    assert response.status_code == 200
    assert reverse("accounts:signup") not in response.content.decode()
