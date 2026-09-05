from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.tests.factories import attach_otp_verification
from apps.audit.models import AuditEvent
from apps.ministries.enums import ContactVerificationStatus
from apps.ministries.models import OfficialContactChallenge
from apps.ministries.services import (
    OfficialContactVerificationError,
    create_publisher,
    is_publisher_active,
    reissue_official_contact_challenge,
    verify_official_contact,
)
from apps.ministries.tests.factories import (
    MinistryOrganizationFactory,
    SuperAdminFactory,
    UserFactory,
)

pytestmark = [pytest.mark.django_db]


@pytest.mark.unit
def test_domain_eligibility_does_not_grant_publisher_access_until_contact_round_trip():
    """AUTH-005, D3: matching the ministry domain is eligibility, not verified official contact."""
    delivered = []
    super_admin = SuperAdminFactory()
    ministry = MinistryOrganizationFactory()
    officer = UserFactory()

    publisher = create_publisher(
        super_admin,
        ministry=ministry,
        user=officer,
        title="Information Officer",
        official_email="officer@moit.gov.np",
        notification_sender=lambda *, publisher, token: delivered.append((publisher.pk, token)),
    )

    assert publisher.contact_verification_status == ContactVerificationStatus.PENDING
    assert not is_publisher_active(officer, ministry)
    assert delivered[0][0] == publisher.pk
    assert OfficialContactChallenge.objects.filter(publisher=publisher).count() == 1
    assert AuditEvent.objects.filter(action="publisher.contact_challenge_issued").exists()


@pytest.mark.integration
def test_valid_contact_token_verifies_once_and_enables_publisher_access():
    """AUTH-005, D3, SEC-008: a one-time official-contact token enables audited publisher access."""
    delivered = []
    super_admin = SuperAdminFactory()
    ministry = MinistryOrganizationFactory()
    officer = UserFactory()
    publisher = create_publisher(
        super_admin,
        ministry=ministry,
        user=officer,
        title="Information Officer",
        official_email="officer@moit.gov.np",
        notification_sender=lambda *, publisher, token: delivered.append(token),
    )

    verified = verify_official_contact(publisher, delivered[0])

    assert verified.contact_verification_status == ContactVerificationStatus.VERIFIED
    assert verified.contact_verified_at is not None
    assert is_publisher_active(officer, ministry)
    challenge = OfficialContactChallenge.objects.get(publisher=publisher)
    assert challenge.consumed_at is not None
    assert challenge.token_digest != delivered[0]
    assert AuditEvent.objects.filter(action="publisher.contact_verified", actor=officer).exists()

    with pytest.raises(OfficialContactVerificationError):
        verify_official_contact(publisher, delivered[0])


@pytest.mark.unit
def test_expired_contact_token_cannot_verify_or_enable_publisher_access():
    """AUTH-005, D3: expired contact challenges are rejected and remain auditable."""
    delivered = []
    super_admin = SuperAdminFactory()
    ministry = MinistryOrganizationFactory()
    officer = UserFactory()
    publisher = create_publisher(
        super_admin,
        ministry=ministry,
        user=officer,
        title="Information Officer",
        official_email="officer@moit.gov.np",
        notification_sender=lambda *, publisher, token: delivered.append(token),
        verification_ttl=timedelta(minutes=1),
    )

    challenge = OfficialContactChallenge.objects.get(publisher=publisher)
    challenge.expires_at = timezone.now() - timedelta(seconds=1)
    challenge.save(update_fields=["expires_at"])

    with pytest.raises(OfficialContactVerificationError):
        verify_official_contact(publisher, delivered[0], now=timezone.now())

    challenge.refresh_from_db()
    assert challenge.expired_at is not None
    assert not is_publisher_active(officer, ministry)
    assert AuditEvent.objects.filter(action="publisher.contact_challenge_expired").exists()


@pytest.mark.integration
def test_reissued_contact_challenge_supersedes_the_prior_token():
    """AUTH-005, D3, SEC-008: reissue invalidates the predecessor and records both states."""
    delivered = []
    super_admin = SuperAdminFactory()
    ministry = MinistryOrganizationFactory()
    officer = UserFactory()
    publisher = create_publisher(
        super_admin,
        ministry=ministry,
        user=officer,
        title="Information Officer",
        official_email="officer@moit.gov.np",
        notification_sender=lambda *, publisher, token: delivered.append(token),
    )
    attach_otp_verification(officer)

    reissued = reissue_official_contact_challenge(
        officer,
        publisher,
        notification_sender=lambda *, publisher, token: delivered.append(token),
    )

    with pytest.raises(OfficialContactVerificationError):
        verify_official_contact(publisher, delivered[0])
    verify_official_contact(publisher, delivered[1])

    assert reissued.status == "pending"
    assert (
        OfficialContactChallenge.objects.filter(publisher=publisher, status="superseded").count()
        == 1
    )
    assert AuditEvent.objects.filter(
        action="publisher.contact_challenge_issued",
        after__superseded_challenge_count=1,
    ).exists()
