import pytest
from django.test import Client
from django.urls import reverse
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.audit.models import AuditEvent
from apps.ministries.enums import OnboardingRequestStatus, OrgStatus
from apps.ministries.models import MinistryOnboardingRequest, MinistryOrganization
from apps.ministries.services import (
    MinistryOnboardingRequestError,
    decline_onboarding_request,
    log_onboarding_request,
    provision_onboarding_request,
)
from apps.ministries.tests.factories import (
    MinistryOrganizationFactory,
    PrivilegedUserFactory,
    SuperAdminFactory,
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


def onboarding_payload(**overrides):
    payload = {
        "name_en": "Ministry of Land Management, Cooperatives and Poverty Alleviation",
        "name_ne": "भूमि व्यवस्था, सहकारी तथा गरिबी निवारण मन्त्रालय",
        "abbreviation": "MoLMCPA",
        "website_url": "https://molmcpa.gov.np",
        "official_email": "sarita.gautam@molmcpa.gov.np",
        "nominated_officer_name": "Sarita Gautam",
        "nominated_officer_title": "Under Secretary, IT Section",
        "purpose": "Land-records viewer accessibility remediation",
        "focal_contact": "Joint Secretary, Planning",
        "nomination_reference": "Chalani no. 2083/05/17-114",
        "signatory_name": "Secretary",
        "signatory_verified": True,
    }
    payload.update(overrides)
    return payload


@pytest.mark.integration
def test_log_onboarding_request_records_checks_and_audit():
    """AUTH-004/SEC-008: a verified Super Admin logs a traceable ministry request."""
    super_admin = SuperAdminFactory()

    request = log_onboarding_request(super_admin, **onboarding_payload())

    assert request.reference.startswith("REQ-")
    assert request.status == OnboardingRequestStatus.NEW
    assert request.domain_verified is True
    assert request.named_person_verified is True
    assert request.signatory_verified is True
    assert request.duplicate_organization is None
    assert AuditEvent.objects.filter(
        action="ministry.onboarding_request.logged", actor=super_admin
    ).exists()


@pytest.mark.integration
def test_log_onboarding_request_rejects_non_government_or_shared_mailbox():
    """AUTH-004: requests require a government domain and a named official mailbox."""
    super_admin = SuperAdminFactory()

    with pytest.raises(MinistryOnboardingRequestError):
        log_onboarding_request(
            super_admin,
            **onboarding_payload(official_email="info@molmcpa.gov.np"),
        )
    with pytest.raises(MinistryOnboardingRequestError):
        log_onboarding_request(
            super_admin,
            **onboarding_payload(website_url="https://example.org"),
        )


@pytest.mark.integration
def test_onboarding_request_detects_existing_organization_and_cannot_provision():
    """AUTH-004: duplicate organization detection prevents a second ministry record."""
    super_admin = SuperAdminFactory()
    existing = MinistryOrganizationFactory(
        name_en="Ministry of Land Management, Cooperatives and Poverty Alleviation",
        slug="molmcpa",
    )
    request = log_onboarding_request(super_admin, **onboarding_payload())

    assert request.duplicate_organization == existing
    with pytest.raises(MinistryOnboardingRequestError):
        provision_onboarding_request(super_admin, request)
    request.refresh_from_db()
    assert request.status == OnboardingRequestStatus.NEW


@pytest.mark.integration
def test_provision_onboarding_request_creates_pending_organization_and_preserves_trail():
    """AUTH-004/SEC-008: approved onboarding provisioning creates the pending organization once."""
    super_admin = SuperAdminFactory()
    request = log_onboarding_request(super_admin, **onboarding_payload())

    ministry = provision_onboarding_request(super_admin, request)

    request.refresh_from_db()
    assert ministry.status == OrgStatus.PENDING
    assert request.status == OnboardingRequestStatus.PROVISIONED
    assert request.provisioned_organization == ministry
    assert MinistryOrganization.objects.filter(pk=ministry.pk).exists()
    assert AuditEvent.objects.filter(
        action="ministry.onboarding_request.provisioned", actor=super_admin
    ).exists()


@pytest.mark.integration
def test_decline_onboarding_request_requires_reason_and_is_audited():
    """AUTH-004/SEC-008: declining retains a reason and attributable audit event."""
    super_admin = SuperAdminFactory()
    request = log_onboarding_request(super_admin, **onboarding_payload())

    declined = decline_onboarding_request(
        super_admin,
        request,
        reason="The nomination letter could not be verified.",
    )

    assert declined.status == OnboardingRequestStatus.DECLINED
    assert declined.decline_reason == "The nomination letter could not be verified."
    assert AuditEvent.objects.filter(
        action="ministry.onboarding_request.declined", actor=super_admin
    ).exists()


@pytest.mark.integration
def test_super_admin_can_log_view_and_provision_onboarding_request(client):
    """AUTH-004: the protected D1.1 screen leads into ministry provisioning."""
    super_admin = SuperAdminFactory()
    verify_mfa(client, super_admin)

    created = client.post(reverse("ministries:onboarding_request_create"), onboarding_payload())
    request = MinistryOnboardingRequest.objects.get()
    detail = client.get(
        reverse("ministries:onboarding_request_detail", kwargs={"reference": request.reference})
    )
    provisioned = client.post(
        reverse("ministries:onboarding_request_provision", kwargs={"reference": request.reference})
    )

    request.refresh_from_db()
    assert created.status_code == 302
    assert detail.status_code == 200
    assert "PMO checks" in detail.content.decode()
    assert provisioned.status_code == 302
    assert request.status == OnboardingRequestStatus.PROVISIONED
    assert provisioned.url == reverse("ministries:organization_list")


@pytest.mark.integration
def test_member_cannot_read_or_act_on_onboarding_requests(client):
    """AUTH-004/AUTH-006: non-Super Admins cannot access the D1.1 onboarding surface."""
    request = log_onboarding_request(SuperAdminFactory(), **onboarding_payload())
    member = PrivilegedUserFactory()
    verify_mfa(client, member)

    response = client.get(
        reverse("ministries:onboarding_request_detail", kwargs={"reference": request.reference})
    )

    assert response.status_code == 403


@pytest.mark.integration
def test_onboarding_provision_requires_csrf():
    """AUTH-004/SEC-008: D1.1 provision action remains protected by Django CSRF."""
    super_admin = SuperAdminFactory()
    request = log_onboarding_request(super_admin, **onboarding_payload())
    client = Client(enforce_csrf_checks=True)
    verify_mfa(client, super_admin)

    response = client.post(
        reverse("ministries:onboarding_request_provision", kwargs={"reference": request.reference})
    )

    request.refresh_from_db()
    assert response.status_code == 403
    assert request.status == OnboardingRequestStatus.NEW
