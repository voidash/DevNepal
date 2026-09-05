import pytest

from apps.audit.models import AuditEvent
from apps.ministries.enums import OrgStatus, PublisherStatus
from apps.ministries.models import MinistryOrganization, MinistryPublisher
from apps.ministries.services import (
    MinistryProvisioningError,
    OfficialContactVerificationError,
    PublisherAssignmentError,
    PublisherLifecycleError,
    activate_organization,
    create_publisher,
    is_publisher_active,
    provision_ministry,
    revoke_organization,
    revoke_publisher,
    suspend_organization,
    suspend_publisher,
    verify_official_contact,
)
from apps.ministries.tests.factories import (
    MinistryOrganizationFactory,
    MinistryPublisherFactory,
    SuperAdminFactory,
    UserFactory,
)

pytestmark = [pytest.mark.django_db]


@pytest.mark.unit
def test_super_admin_provisions_ministry_organization():
    """AUTH-004: Super Admin provisions a PENDING organization with attribution and audit."""
    super_admin = SuperAdminFactory()

    org = provision_ministry(
        super_admin,
        name_en="Ministry of Communication and Information Technology",
        name_ne="सूचना तथा सञ्चार प्रविधि मन्त्रालय",
        website_url="https://www.moit.gov.np",
        contact_email="info@moit.gov.np",
    )

    assert org.status == OrgStatus.PENDING
    assert org.provisioned_by == super_admin
    assert org.provisioned_at is not None
    assert org.slug == "ministry-of-communication-and-information-technology"

    event = AuditEvent.objects.get(action="ministry.created")
    assert event.actor == super_admin
    assert event.object_id == str(org.pk)
    assert event.after["status"] == OrgStatus.PENDING
    assert event.after["slug"] == org.slug


@pytest.mark.unit
def test_provisioning_denied_without_super_admin():
    """AUTH-004, AUTH-006, SEC-008: non-super-admin provisioning is denied and audited."""
    intruder = UserFactory()

    with pytest.raises(MinistryProvisioningError):
        provision_ministry(intruder, name_en="Fake Ministry", website_url="https://fake.gov.np")

    assert not MinistryOrganization.objects.filter(name_en="Fake Ministry").exists()
    event = AuditEvent.objects.get(action="ministry.create.denied")
    assert event.actor == intruder
    assert event.result == "failure"


@pytest.mark.unit
def test_provisioning_denied_without_otp_verified_super_admin():
    """AUTH-005/SEC-008: an unverified Super Admin cannot provision a ministry and is audited."""
    super_admin = SuperAdminFactory()
    super_admin.otp_device = None
    super_admin.is_verified = lambda: False

    with pytest.raises(MinistryProvisioningError):
        provision_ministry(super_admin, name_en="Ministry of MFA", website_url="https://mfa.gov.np")

    assert not MinistryOrganization.objects.filter(name_en="Ministry of MFA").exists()
    assert AuditEvent.objects.filter(
        actor=super_admin, action="ministry.create.denied", result="failure"
    ).exists()


@pytest.mark.unit
def test_provision_rejects_duplicate_slug():
    """AUTH-004, DSC-003: provisioning refuses a duplicate slug; slugs stay unique and stable."""
    super_admin = SuperAdminFactory()
    provision_ministry(super_admin, name_en="Ministry of Finance", slug="finance")

    with pytest.raises(MinistryProvisioningError):
        provision_ministry(super_admin, name_en="Another Finance", slug="finance")


@pytest.mark.unit
def test_organization_activation_and_terminal_states():
    """AUTH-004: Super Admin activates an organization; revocation is terminal."""
    super_admin = SuperAdminFactory()
    org = provision_ministry(super_admin, name_en="Ministry of Education")

    activated = activate_organization(super_admin, org)
    assert activated.status == OrgStatus.ACTIVE
    assert AuditEvent.objects.filter(action="ministry.activated", actor=super_admin).exists()

    revoked = revoke_organization(super_admin, org, reason="mandate withdrawn")
    assert revoked.status == OrgStatus.REVOKED
    assert revoked.revocation_reason == "mandate withdrawn"
    assert revoked.revoked_at is not None

    with pytest.raises(MinistryProvisioningError):
        activate_organization(super_admin, revoked)


@pytest.mark.unit
def test_suspending_organization_blocks_its_publishers():
    """AUTH-004: suspending an organization deactivates its publisher accounts."""
    super_admin = SuperAdminFactory()
    org = MinistryOrganizationFactory(status=OrgStatus.ACTIVE)
    publishers = MinistryPublisherFactory.create_batch(2, ministry=org)
    assert all(is_publisher_active(p.user, org) for p in publishers)

    suspended = suspend_organization(super_admin, org, reason="under investigation")

    assert suspended.status == OrgStatus.SUSPENDED
    assert suspended.suspension_reason == "under investigation"
    assert suspended.suspended_at is not None
    assert not any(is_publisher_active(p.user, org) for p in publishers)
    event = AuditEvent.objects.get(action="ministry.suspended")
    assert event.before["status"] == OrgStatus.ACTIVE
    assert event.after["status"] == OrgStatus.SUSPENDED


@pytest.mark.unit
@pytest.mark.parametrize("org_status", [OrgStatus.PENDING, OrgStatus.SUSPENDED, OrgStatus.REVOKED])
def test_non_active_organization_yields_no_active_publisher(org_status):
    """AUTH-004, BR-001: only an ACTIVE organization grants active publisher standing."""
    org = MinistryOrganizationFactory(status=org_status)
    publisher = MinistryPublisherFactory(ministry=org)

    assert not is_publisher_active(publisher.user, org)
    assert not is_publisher_active(UserFactory(), org)


@pytest.mark.unit
def test_create_publisher_verifies_official_email_domain():
    """AUTH-005, D3: official email domain must match the ministry's website domain."""
    super_admin = SuperAdminFactory()
    org = MinistryOrganizationFactory(
        status=OrgStatus.ACTIVE, website_url="https://www.moit.gov.np"
    )
    officer = UserFactory()

    publisher = create_publisher(
        super_admin,
        ministry=org,
        user=officer,
        title="Information Officer",
        official_email="officer@moit.gov.np",
    )
    assert publisher.official_email == "officer@moit.gov.np"

    outsider = UserFactory()
    with pytest.raises(OfficialContactVerificationError):
        create_publisher(
            super_admin,
            ministry=org,
            user=outsider,
            title="Information Officer",
            official_email="officer@gmail.com",
        )
    assert not MinistryPublisher.objects.filter(user=outsider, ministry=org).exists()


@pytest.mark.unit
def test_create_publisher_requires_official_domain_source():
    """AUTH-005, D3: no website means no official domain to verify against."""
    super_admin = SuperAdminFactory()
    org = MinistryOrganizationFactory(status=OrgStatus.ACTIVE, website_url="")

    with pytest.raises(OfficialContactVerificationError):
        create_publisher(
            super_admin,
            ministry=org,
            user=UserFactory(),
            title="Information Officer",
            official_email="officer@moit.gov.np",
        )


@pytest.mark.integration
def test_create_publisher_records_attestation_in_audit():
    """AUTH-005, D3, SEC-008: contact verification attestation is recorded in audit."""
    super_admin = SuperAdminFactory()
    org = MinistryOrganizationFactory(status=OrgStatus.ACTIVE, website_url="https://moit.gov.np")
    officer = UserFactory()

    create_publisher(
        super_admin,
        ministry=org,
        user=officer,
        title="Information Officer",
        official_email="officer@moit.gov.np",
    )

    event = AuditEvent.objects.get(action="publisher.granted")
    assert event.actor == super_admin
    assert event.after["official_email"] == "officer@moit.gov.np"
    assert event.after["official_domain"] == "moit.gov.np"
    assert event.after["official_domain_eligible"] is True
    assert event.after["official_domain_attested_by"] == super_admin.username
    assert event.after["contact_verification_status"] == "pending"


@pytest.mark.unit
def test_regrant_publisher_creates_new_active_assignment_after_revocation():
    """AUTH-004, D14: revocation remains historical and a re-grant creates a new assignment."""
    super_admin = SuperAdminFactory()
    org = MinistryOrganizationFactory(status=OrgStatus.ACTIVE)
    officer = UserFactory()
    create_publisher(
        super_admin,
        ministry=org,
        user=officer,
        title="Information Officer",
        official_email="officer@moit.gov.np",
    )

    with pytest.raises(PublisherAssignmentError):
        create_publisher(
            super_admin,
            ministry=org,
            user=officer,
            title="Second Officer",
            official_email="officer2@moit.gov.np",
        )

    revoked = revoke_publisher(
        super_admin,
        MinistryPublisher.objects.get(user=officer, ministry=org),
        reason="transferred",
    )
    assert revoked.status == PublisherStatus.REVOKED

    regranted = create_publisher(
        super_admin,
        ministry=org,
        user=officer,
        title="Information Officer",
        official_email="officer@moit.gov.np",
    )

    assert regranted.pk != revoked.pk
    assert regranted.status == PublisherStatus.ACTIVE
    assert MinistryPublisher.objects.filter(user=officer, ministry=org).count() == 2
    assert AuditEvent.objects.filter(action="publisher.revoked", object_id=str(revoked.pk)).exists()
    assert AuditEvent.objects.filter(
        action="publisher.granted", object_id=str(regranted.pk)
    ).exists()


@pytest.mark.unit
def test_create_publisher_rejected_for_dead_ministry():
    """AUTH-004: publishers cannot be granted against suspended or revoked organizations."""
    super_admin = SuperAdminFactory()
    for status in (OrgStatus.SUSPENDED, OrgStatus.REVOKED):
        org = MinistryOrganizationFactory(status=status)
        with pytest.raises(PublisherAssignmentError):
            create_publisher(
                super_admin,
                ministry=org,
                user=UserFactory(),
                title="Information Officer",
                official_email="officer@moit.gov.np",
            )


@pytest.mark.unit
def test_suspend_publisher_removes_access_immediately():
    """AUTH-009, SEC-008: a suspended publisher loses access immediately, with reason and audit."""
    super_admin = SuperAdminFactory()
    org = MinistryOrganizationFactory(status=OrgStatus.ACTIVE)
    publisher = MinistryPublisherFactory(ministry=org)
    assert is_publisher_active(publisher.user, org)

    suspended = suspend_publisher(super_admin, publisher, reason="pending investigation")

    assert suspended.user.is_active is False
    assert not is_publisher_active(suspended.user, org)
    event = AuditEvent.objects.get(action="publisher.suspended")
    assert event.actor == super_admin
    assert event.before["user_is_active"] is True
    assert event.after["user_is_active"] is False
    assert event.after["reason"] == "pending investigation"


@pytest.mark.integration
def test_revoke_publisher_leaves_other_intact():
    """AUTH-004, A1: revoking one publisher leaves the other intact; both audited."""
    super_admin = SuperAdminFactory()
    org = MinistryOrganizationFactory(status=OrgStatus.ACTIVE)
    first = create_publisher(
        super_admin,
        ministry=org,
        user=UserFactory(),
        title="Information Officer",
        official_email="officer1@moit.gov.np",
    )
    delivered = []
    second = create_publisher(
        super_admin,
        ministry=org,
        user=UserFactory(),
        title="Information Officer",
        official_email="officer2@moit.gov.np",
        notification_sender=lambda *, publisher, token: delivered.append(token),
    )
    verify_official_contact(second, delivered[0])

    revoked = revoke_publisher(super_admin, first, reason="rotated out")

    assert revoked.status == PublisherStatus.REVOKED
    assert revoked.revoked_by == super_admin
    assert revoked.revoked_at is not None
    assert revoked.revocation_reason == "rotated out"
    assert not is_publisher_active(revoked.user, org)

    second.refresh_from_db()
    assert second.status == PublisherStatus.ACTIVE
    assert is_publisher_active(second.user, org)

    assert AuditEvent.objects.filter(action="publisher.revoked", object_id=str(first.pk)).exists()
    assert AuditEvent.objects.filter(action="publisher.granted", object_id=str(second.pk)).exists()


@pytest.mark.unit
def test_publisher_lifecycle_requires_reason_and_single_use():
    """AUTH-004, AUTH-009: revocation needs a reason, cannot repeat, and needs a Super Admin."""
    super_admin = SuperAdminFactory()
    org = MinistryOrganizationFactory(status=OrgStatus.ACTIVE)
    publisher = MinistryPublisherFactory(ministry=org)

    with pytest.raises(PublisherLifecycleError):
        revoke_publisher(super_admin, publisher, reason="   ")

    revoked = revoke_publisher(super_admin, publisher, reason="rotated out")
    with pytest.raises(PublisherLifecycleError):
        revoke_publisher(super_admin, revoked, reason="again")

    other = MinistryPublisherFactory(ministry=org)
    with pytest.raises(MinistryProvisioningError):
        revoke_publisher(UserFactory(), other, reason="unauthorized")


@pytest.mark.integration
def test_full_provisioning_trail_complete():
    """A1, SEC-008: provisioning and revoking publishers leaves a complete attributable trail."""
    super_admin = SuperAdminFactory()
    org = provision_ministry(
        super_admin,
        name_en="Ministry of Health and Population",
        slug="mohp",
        website_url="https://mohp.gov.np",
    )
    activate_organization(super_admin, org)
    delivered = []
    officers = [
        create_publisher(
            super_admin,
            ministry=org,
            user=UserFactory(username=f"officer{i}"),
            title="Information Officer",
            official_email=f"officer{i}@mohp.gov.np",
            notification_sender=lambda *, publisher, token: delivered.append((publisher.pk, token)),
        )
        for i in range(2)
    ]
    for publisher in officers:
        verify_official_contact(
            publisher,
            next(token for publisher_id, token in delivered if publisher_id == publisher.pk),
        )

    revoke_publisher(super_admin, officers[0], reason="rotated out")

    assert not is_publisher_active(officers[0].user, org)
    assert is_publisher_active(officers[1].user, org)

    trail = list(
        AuditEvent.objects.filter(
            action__in=[
                "ministry.created",
                "ministry.activated",
                "publisher.granted",
                "publisher.revoked",
            ]
        )
    )
    assert len(trail) == 5
    assert all(event.actor == super_admin for event in trail)
