import pytest
from django.urls import reverse

from apps.accounts.models import UserSession
from apps.accounts.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.mark.unit
def test_auth001_login_is_explicitly_for_ministry_publishers(client):
    """AUTH-001/AUTH-002: the only visible local identity boundary is ministry publishing."""
    response = client.get(reverse("accounts:login"))
    content = response.content.decode()

    assert response.status_code == 200
    assert "Ministry Publisher sign in" in content
    assert "account issued for your ministry" in content
    assert "Visitors and contributors do not need an account" in content
    assert "GitHub connection" not in content


@pytest.mark.unit
def test_auth001_signup_explains_public_and_private_account_fields(client):
    """AUTH-001/AUTH-008/MEM-001: account creation labels public username and private email."""
    response = client.get(reverse("accounts:signup"))
    content = response.content.decode()

    assert response.status_code == 200
    assert "Public profile address" in content
    assert "Private · always" in content
    assert "Email and sign-in provider are never shown publicly" in content
    assert "Profile and visibility" in content


@pytest.mark.unit
def test_mem002_profile_screen_groups_fields_and_field_level_visibility(client):
    """MEM-002/MEM-003/MEM-008/REC-004: profile editing mirrors profile and visibility steps."""
    user = UserFactory(username="profile-controls")
    client.force_login(user)

    response = client.get(reverse("accounts:profile_edit"))
    content = response.content.decode()

    assert response.status_code == 200
    assert '<h1 id="profile-visibility-heading">Profile & visibility</h1>' in content
    assert "Choose visibility field by field" in content
    assert "Email and sign-in provider stay private" in content
    assert "Preview as a visitor" in content
    assert "Recognition settings" in content
    assert reverse("notifications:email_preferences") in content
    assert reverse("recognition:my_profile") in content


@pytest.mark.unit
def test_auth008_dashboard_is_account_control_hub_for_connections_preferences_and_data(client):
    """AUTH-008/AUTH-010/GIT-002/NTF-002/REC-004: dashboard links every account control."""
    user = UserFactory(username="account-controls")
    client.force_login(user)

    response = client.get(reverse("accounts:dashboard"))
    content = response.content.decode()

    assert response.status_code == 200
    assert "Connections & data" in content
    assert "Connecting GitHub is optional" in content
    assert "Email preferences" in content
    assert "Recognition settings" in content
    for route in (
        reverse("accounts:profile_edit"),
        reverse("accounts:session_list"),
        reverse("accounts:privacy_export"),
        reverse("notifications:email_preferences"),
        reverse("recognition:my_profile"),
    ):
        assert route in content


@pytest.mark.unit
def test_auth007_sessions_screen_explains_current_device_control(client):
    """AUTH-007/AUTH-008: sessions list explains revocation and keeps account controls linked."""
    user = UserFactory(username="session-controls")
    UserSession.objects.create(user=user, session_key="current-browser", device_label="Firefox")
    client.force_login(user)

    response = client.get(reverse("accounts:session_list"))
    content = response.content.decode()

    assert response.status_code == 200
    assert "Signed-in devices" in content
    assert "Revoke any session you do not recognise" in content
    assert reverse("accounts:dashboard") in content
    assert reverse("accounts:privacy_export") in content
