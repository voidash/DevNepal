import pytest
from django.urls import reverse

from apps.administration.models import FeatureFlag
from apps.administration.services import (
    AdministrationAuthorizationError,
    create_feature_flag,
    flag_enabled,
    set_feature_flag,
)
from apps.administration.tests.factories import FeatureFlagFactory
from apps.audit.models import AuditEvent
from apps.audit.tests.factories import UserFactory
from apps.ministries.tests.factories import SuperAdminFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _privileged_mfa_bypass(settings):
    settings.PRIVILEGED_MFA_BYPASS = True


@pytest.mark.unit
def test_an_unregistered_capability_reads_as_off():
    """ADM-001: an unknown capability defaults to off rather than silently enabled."""
    assert flag_enabled("not-registered") is False


@pytest.mark.unit
def test_a_registered_capability_reports_its_state():
    """ADM-001: the switch a Super Admin set is what the platform reads back."""
    flag = FeatureFlagFactory(key="official-blogs", is_enabled=False)

    assert flag_enabled("official-blogs") is False

    set_feature_flag(SuperAdminFactory(), flag, is_enabled=True)

    assert flag_enabled("official-blogs") is True


@pytest.mark.integration
def test_switching_a_capability_is_audited_against_the_named_super_admin():
    """ADM-001/ADM-008: capability changes leave an attributable audit record."""
    super_admin = SuperAdminFactory()
    flag = FeatureFlagFactory(key="leaderboard", is_enabled=False)

    set_feature_flag(super_admin, flag, is_enabled=True)

    event = AuditEvent.objects.get(action="administration.feature_flag_change_applied")
    assert event.actor == super_admin
    assert event.before["is_enabled"] is False
    assert event.after["to_enabled"] is True
    assert event.after["proposed_by"] == super_admin.username
    assert event.result == "success"


@pytest.mark.integration
def test_a_member_cannot_switch_a_capability_and_the_attempt_is_recorded():
    """ADM-001/SEC-005: an unauthorized toggle is refused and logged as denied."""
    flag = FeatureFlagFactory(is_enabled=False)

    with pytest.raises(AdministrationAuthorizationError):
        set_feature_flag(UserFactory(), flag, is_enabled=True)

    flag.refresh_from_db()
    assert flag.is_enabled is False
    assert AuditEvent.objects.filter(
        action="administration.feature_flag_change", result="denied"
    ).exists()


@pytest.mark.integration
def test_a_new_capability_starts_switched_off():
    """ADM-001: registering a switch never enables it as a side effect."""
    flag = create_feature_flag(SuperAdminFactory(), key="new-capability", label="New capability")

    assert flag.is_enabled is False
    assert AuditEvent.objects.filter(action="administration.feature_flag_create").exists()


@pytest.mark.integration
def test_member_cannot_reach_the_feature_flag_page(client):
    """ADM-001/SEC-005: capability management is Super Admin only."""
    client.force_login(UserFactory())

    assert client.get(reverse("administration:feature_flags")).status_code == 403


@pytest.mark.integration
def test_super_admin_toggles_a_capability_from_the_page(client):
    """ADM-001: the feature flag page switches a capability and returns to the list."""
    FeatureFlagFactory(key="ministry-reporting", is_enabled=False)
    client.force_login(SuperAdminFactory())

    response = client.post(
        reverse("administration:feature_flag_change", args=["ministry-reporting"]),
        {"reason": "Enabling ministry reporting for the pilot."},
    )

    assert response.status_code == 302
    assert response.url == reverse("administration:feature_flags")
    assert FeatureFlag.objects.get(key="ministry-reporting").is_enabled is True


@pytest.mark.integration
def test_toggling_rejects_a_get_request(client):
    """SEC-005/D5.7: a capability cannot be switched by following a link."""
    FeatureFlagFactory(key="read-only-attempt")
    client.force_login(SuperAdminFactory())

    response = client.get(reverse("administration:feature_flag_change", args=["read-only-attempt"]))

    assert response.status_code == 405
    assert FeatureFlag.objects.get(key="read-only-attempt").is_enabled is False


@pytest.mark.integration
def test_a_super_admin_without_mfa_cannot_switch_a_capability(settings):
    """ADM-001/AUTH-005: the service refuses an unverified session, not just the view."""
    from apps.administration.services import AdministrationMFARequiredError

    settings.PRIVILEGED_MFA_BYPASS = False
    super_admin = SuperAdminFactory()
    super_admin.is_verified = lambda: False
    flag = FeatureFlagFactory(key="unverified-attempt", is_enabled=False)

    with pytest.raises(AdministrationMFARequiredError):
        set_feature_flag(super_admin, flag, is_enabled=True)

    flag.refresh_from_db()
    assert flag.is_enabled is False
