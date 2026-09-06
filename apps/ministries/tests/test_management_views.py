import pytest
from django.test import Client
from django.urls import reverse
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.audit.models import AuditEvent
from apps.ministries.enums import ContactVerificationStatus, OrgStatus
from apps.ministries.models import (
    MinistryOnboardingRequest,
    MinistryOrganization,
    MinistryPublisher,
)
from apps.ministries.services import create_publisher
from apps.ministries.tests.factories import (
    MinistryOrganizationFactory,
    MinistryPublisherFactory,
    SuperAdminFactory,
    UserFactory,
)

pytestmark = [pytest.mark.django_db, pytest.mark.urls("apps.ministries.tests.urls")]


def verify_mfa(client, user):
    client.force_login(user)
    setup_url = reverse("accounts:mfa_setup")
    client.get(setup_url)
    csrf_token = client.cookies.get("csrftoken")
    headers = {"HTTP_X_CSRFTOKEN": csrf_token.value} if csrf_token else {}
    device = TOTPDevice.objects.filter(user=user).first()
    if device is None:
        client.post(setup_url, {"action": "enroll"}, **headers)
        device = TOTPDevice.objects.get(user=user)
    token = totp(
        device.bin_key,
        step=device.step,
        t0=device.t0,
        digits=device.digits,
        drift=device.drift,
    )
    assert client.post(setup_url, {"token": token}, **headers).status_code == 302


@pytest.mark.integration
def test_legacy_organization_create_route_funnels_to_onboarding_request(client):
    """AUTH-004/D1.1: direct ministry creation uses the accountable request flow."""
    super_admin = SuperAdminFactory()
    verify_mfa(client, super_admin)

    response = client.get(reverse("ministries:organization_create"))

    assert response.status_code == 302
    assert response.url == reverse("ministries:onboarding_request_create")


@pytest.mark.integration
def test_verified_super_admin_manages_ministries_and_named_publishers(client, mailoutbox):
    """AUTH-004/AUTH-005/ADM-001: Super Admin provisions, activates, and grants named officers."""
    super_admin = SuperAdminFactory()
    officer = UserFactory(username="officer")
    verify_mfa(client, super_admin)

    created = client.post(
        reverse("ministries:onboarding_request_create"),
        {
            "name_en": "Ministry of Health",
            "name_ne": "स्वास्थ्य मन्त्रालय",
            "website_url": "https://mohp.gov.np",
            "official_email": "officer@mohp.gov.np",
            "nominated_officer_name": "Health Officer",
            "nominated_officer_title": "Information Officer",
            "purpose": "Health technology coordination",
            "focal_contact": "Health Secretary",
            "nomination_reference": "MOHP-2026-001",
            "signatory_name": "Health Secretary",
            "signatory_verified": True,
        },
    )
    onboarding_request = MinistryOnboardingRequest.objects.get()
    provisioned = client.post(
        reverse(
            "ministries:onboarding_request_provision",
            kwargs={"reference": onboarding_request.reference},
        )
    )
    ministry = MinistryOrganization.objects.get(name_en="Ministry of Health")
    activated = client.post(
        reverse("ministries:organization_action", kwargs={"slug": ministry.slug}),
        {"action": "activate"},
    )
    granted = client.post(
        reverse("ministries:publisher_create", kwargs={"slug": ministry.slug}),
        {
            "user": officer.pk,
            "title": "Information Officer",
            "official_email": "officer@mohp.gov.np",
        },
    )

    ministry.refresh_from_db()
    publisher = MinistryPublisher.objects.get(ministry=ministry, user=officer)
    detail = client.get(reverse("ministries:organization_detail", kwargs={"slug": ministry.slug}))
    assert created.status_code == 302
    assert provisioned.status_code == 302
    assert activated.status_code == 302
    assert granted.status_code == 302
    assert ministry.status == OrgStatus.ACTIVE
    assert publisher.contact_verification_status == ContactVerificationStatus.PENDING
    assert "Health Officer" in detail.content.decode()
    assert "officer@mohp.gov.np" in detail.content.decode()
    assert len(mailoutbox) == 1
    assert AuditEvent.objects.filter(action="ministry.created", actor=super_admin).exists()
    assert AuditEvent.objects.filter(action="publisher.granted", actor=super_admin).exists()


@pytest.mark.integration
def test_non_super_admin_cannot_manage_ministries(client):
    """AUTH-004/AUTH-006: publisher and member requests cannot access management routes."""
    ministry = MinistryOrganizationFactory()
    publisher = MinistryPublisherFactory(ministry=ministry)
    verify_mfa(client, publisher.user)

    response = client.get(reverse("ministries:organization_list"))

    assert response.status_code == 403


@pytest.mark.integration
def test_official_contact_confirmation_requires_owner_mfa_and_csrf(client):
    """AUTH-005/D3/SEC-008: only the MFA-verified officer can confirm an emailed token."""
    super_admin = SuperAdminFactory()
    ministry = MinistryOrganizationFactory()
    officer = UserFactory(username="officer")
    delivered = []
    create_publisher(
        super_admin,
        ministry=ministry,
        user=officer,
        title="Information Officer",
        official_email="officer@moit.gov.np",
        notification_sender=lambda *, publisher, token: delivered.append(token),
    )
    publisher = MinistryPublisher.objects.get(user=officer)
    token = delivered[0]
    confirmation_url = reverse(
        "ministries:contact_confirmation", kwargs={"publisher_id": publisher.pk}
    )
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(officer)

    mfa_required = csrf_client.get(confirmation_url, {"token": token})
    csrf_rejected = csrf_client.post(confirmation_url, {"token": token})
    verify_mfa(csrf_client, officer)
    confirmed = csrf_client.post(
        confirmation_url,
        {"token": token},
        HTTP_X_CSRFTOKEN=csrf_client.cookies["csrftoken"].value,
    )

    publisher.refresh_from_db()
    assert mfa_required.status_code == 302
    assert csrf_rejected.status_code == 403
    assert confirmed.status_code == 302
    assert publisher.contact_verification_status == ContactVerificationStatus.VERIFIED
    assert AuditEvent.objects.filter(action="publisher.contact_verified", actor=officer).exists()


@pytest.mark.integration
def test_official_contact_confirmation_hides_other_publishers(client):
    """AUTH-006/SEC-005: one publisher cannot inspect or confirm another publisher's challenge."""
    assignment = MinistryPublisherFactory(
        contact_verification_status=ContactVerificationStatus.PENDING
    )
    foreign_assignment = MinistryPublisherFactory()
    verify_mfa(client, foreign_assignment.user)

    response = client.get(
        reverse("ministries:contact_confirmation", kwargs={"publisher_id": assignment.pk}),
        {"token": "forged"},
    )

    assert response.status_code == 404


@pytest.mark.integration
def test_super_admin_actions_reject_requests_without_csrf_token():
    """AUTH-004/SEC-008: ministry lifecycle changes retain Django CSRF protection."""
    super_admin = SuperAdminFactory()
    ministry = MinistryOrganizationFactory(status=OrgStatus.PENDING)
    client = Client(enforce_csrf_checks=True)
    verify_mfa(client, super_admin)

    response = client.post(
        reverse("ministries:organization_action", kwargs={"slug": ministry.slug}),
        {"action": "activate"},
    )

    ministry.refresh_from_db()
    assert response.status_code == 403
    assert ministry.status == OrgStatus.PENDING
