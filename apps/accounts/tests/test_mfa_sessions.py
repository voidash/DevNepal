import pytest
from django.db import IntegrityError
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.accounts.models import UserSession
from apps.accounts.services import PrivilegedMFARequiredError, require_privileged_mfa
from apps.accounts.tests.factories import UserFactory, UserSessionFactory
from apps.audit.models import AuditEvent

pytestmark = pytest.mark.django_db


@pytest.mark.unit
def test_auth007_session_rows_track_device_and_revocation():
    """AUTH-007: device/session rows carry session key, device label, and revocation state."""
    user = UserFactory(username="sita")
    session = UserSessionFactory(user=user, device_label="Firefox on Linux")
    assert session.session_key
    assert len(session.session_key) <= 40
    assert session.revoked_at is None
    assert session.last_activity is None
    assert str(session) == "sita on Firefox on Linux"

    unlabeled = UserSessionFactory(user=user, device_label="")
    assert str(unlabeled) == "sita on device"


@pytest.mark.unit
def test_auth007_session_key_unique():
    """AUTH-007: a session key identifies exactly one device/session row."""
    UserSessionFactory(session_key="a" * 40)
    with pytest.raises(IntegrityError):
        UserSessionFactory(session_key="a" * 40)


@pytest.mark.unit
def test_auth007_raw_ip_addresses_never_stored():
    """AUTH-007, §9.2, ANL-001: session rows store only a salted hash slot, never a raw IP."""
    session = UserSessionFactory()
    stored = UserSession.objects.get(pk=session.pk)
    assert stored.ip_hash == ""
    ip_fields = [
        field.name for field in type(session)._meta.get_fields() if field.name.startswith("ip")
    ]
    assert ip_fields == ["ip_hash"]


@pytest.mark.unit
def test_auth005_service_boundary_requires_a_session_verified_totp_device():
    """AUTH-005/SEC-008: privileged service boundaries require verified MFA and audit denial."""
    actor = UserFactory(is_superuser=True, is_staff=True)

    with pytest.raises(PrivilegedMFARequiredError):
        require_privileged_mfa(actor, action="test.privileged")

    assert AuditEvent.objects.filter(
        actor=actor, action="test.privileged.denied", result="failure"
    ).exists()

    device = TOTPDevice.objects.create(user=actor, name="devnepal")
    actor.otp_device = device
    actor.is_verified = lambda: True

    require_privileged_mfa(actor, action="test.privileged")
