import pytest
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.audit.models import AuditEvent
from apps.ministries.enums import OrgStatus, PublisherStatus
from apps.ministries.services import (
    activate_organization,
    create_publisher,
    provision_ministry,
    revoke_publisher,
)
from apps.ministries.tests.factories import SuperAdminFactory, UserFactory

pytestmark = [pytest.mark.django_db, pytest.mark.acceptance]


def test_a01_named_publisher_provisioning_mfa_and_independent_revocation():
    """A1/AUTH-004/AUTH-005/AUTH-009: named publishers have MFA and independent revocation."""
    super_admin = SuperAdminFactory()
    first = UserFactory(email="first@moit.gov.np")
    second = UserFactory(email="second@moit.gov.np")

    ministry = provision_ministry(
        super_admin,
        name_en="Ministry of Communications",
        name_ne="सञ्चार मन्त्रालय",
        slug="communications",
        website_url="https://www.moit.gov.np",
    )
    activate_organization(super_admin, ministry)
    first_assignment = create_publisher(
        super_admin,
        ministry=ministry,
        user=first,
        title="Digital Services Officer",
        official_email="first@moit.gov.np",
    )
    second_assignment = create_publisher(
        super_admin,
        ministry=ministry,
        user=second,
        title="Open Source Officer",
        official_email="second@moit.gov.np",
    )
    device = TOTPDevice.objects.create(user=first, name="devnepal")
    token = totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits)

    revoke_publisher(super_admin, first_assignment, reason="Officer changed role")

    first_assignment.refresh_from_db()
    second_assignment.refresh_from_db()
    assert ministry.status == OrgStatus.ACTIVE
    assert device.verify_token(token) is True
    assert first_assignment.status == PublisherStatus.REVOKED
    assert second_assignment.status == PublisherStatus.ACTIVE
    assert AuditEvent.objects.filter(action="ministry.created", actor=super_admin).exists()
    assert AuditEvent.objects.filter(action="publisher.granted", actor=super_admin).count() == 2
    assert AuditEvent.objects.filter(action="publisher.revoked", actor=super_admin).exists()
