import json

import pytest
from django.test import override_settings
from django.urls import reverse
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.audit.models import AuditEvent
from apps.audit.services import record_audit
from apps.ministries.tests.factories import SuperAdminFactory, UserFactory
from apps.moderation.enums import CaseStatus
from apps.moderation.services import (
    EXPORT_MIN_PURPOSE_LENGTH,
    EXPORT_RATE_LIMIT,
)
from apps.moderation.tests.factories import ModerationCaseFactory

pytestmark = pytest.mark.django_db

VALID_PURPOSE = "Quarterly oversight review of spam enforcement for this case"


@pytest.fixture(autouse=True)
def moderation_urlconf():
    with override_settings(ROOT_URLCONF="apps.moderation.tests.urls"):
        yield


def verify_mfa(client, user):
    client.force_login(user)
    setup_url = reverse("accounts:mfa_setup")
    client.get(setup_url)
    device = TOTPDevice.objects.get(user=user)
    token = totp(
        device.bin_key,
        step=device.step,
        t0=device.t0,
        digits=device.digits,
        drift=device.drift,
    )
    response = client.post(setup_url, {"token": token})
    assert response.status_code == 302


def export_url(case):
    return reverse("moderation:case_export", kwargs={"pk": case.pk})


@pytest.mark.integration
def test_member_is_denied_case_export(client):
    """ADM-005/SEC-005: privileged case export is access-controlled to Super Admins."""
    case = ModerationCaseFactory()
    client.force_login(UserFactory())

    response = client.post(export_url(case), {"purpose": VALID_PURPOSE})

    assert response.status_code == 403
    assert not AuditEvent.objects.filter(action__startswith="moderation.case.export").exists()


@pytest.mark.integration
def test_unverified_super_admin_is_redirected_from_case_export(client):
    """AUTH-005/ADM-005: export requires an OTP-verified privileged session."""
    case = ModerationCaseFactory()
    super_admin = SuperAdminFactory()
    super_admin.otp_device = None
    super_admin.is_verified = lambda: False
    client.force_login(super_admin)

    response = client.post(export_url(case), {"purpose": VALID_PURPOSE})

    assert response.status_code == 302
    assert response.url == reverse("accounts:mfa_setup")
    assert not AuditEvent.objects.filter(action__startswith="moderation.case.export").exists()


@pytest.mark.integration
def test_missing_purpose_is_refused_and_audited(client):
    """ADM-005/SEC-008: a purposeless export is refused and the refusal is audited."""
    case = ModerationCaseFactory()
    super_admin = SuperAdminFactory()
    verify_mfa(client, super_admin)

    response = client.post(export_url(case), {"purpose": "   "})

    assert response.status_code == 400
    assert AuditEvent.objects.filter(
        action="moderation.case.export.denied", actor=super_admin, result="failure"
    ).exists()
    assert not AuditEvent.objects.filter(action="moderation.case.export").exists()


@pytest.mark.integration
def test_below_minimum_purpose_is_refused_and_audited(client):
    """ADM-005: a purpose shorter than the structured minimum is not a justification."""
    case = ModerationCaseFactory()
    super_admin = SuperAdminFactory()
    verify_mfa(client, super_admin)

    response = client.post(export_url(case), {"purpose": "a" * (EXPORT_MIN_PURPOSE_LENGTH - 1)})

    assert response.status_code == 400
    assert AuditEvent.objects.filter(
        action="moderation.case.export.denied", actor=super_admin, result="failure"
    ).exists()
    assert not AuditEvent.objects.filter(action="moderation.case.export").exists()


@pytest.mark.integration
def test_successful_export_downloads_confidential_case_json_and_audits(client):
    """ADM-005/SEC-008: a purpose-limited export downloads the case record and the audit
    entry carries the purpose and case id — never the payload content."""
    case = ModerationCaseFactory(status=CaseStatus.UNDER_REVIEW)
    case.report.details = "SECRET-REPORT-DETAILS"
    case.report.save(update_fields=["details"])
    super_admin = SuperAdminFactory()
    verify_mfa(client, super_admin)

    response = client.post(export_url(case), {"purpose": VALID_PURPOSE})

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("application/json")
    assert "attachment" in response.headers["Content-Disposition"]
    payload = response.json()
    assert payload["case"]["id"] == case.pk
    assert payload["case"]["status"] == CaseStatus.UNDER_REVIEW
    assert payload["report"]["details"] == "SECRET-REPORT-DETAILS"
    audit = AuditEvent.objects.get(action="moderation.case.export", actor=super_admin)
    assert audit.after == {"purpose": VALID_PURPOSE}
    assert audit.object_id == str(case.pk)
    assert audit.result == "success"
    dumped = json.dumps({"before": audit.before, "after": audit.after})
    assert "SECRET-REPORT-DETAILS" not in dumped


@pytest.mark.integration
def test_export_purpose_never_leaks_into_the_response(client):
    """ADM-005: the declared purpose is recorded only in the audit log, never echoed back."""
    case = ModerationCaseFactory()
    super_admin = SuperAdminFactory()
    verify_mfa(client, super_admin)

    response = client.post(export_url(case), {"purpose": VALID_PURPOSE})

    assert response.status_code == 200
    assert VALID_PURPOSE not in response.content.decode()
    for value in response.headers.values():
        assert VALID_PURPOSE not in value


@pytest.mark.integration
def test_export_rate_limit_returns_429_without_exporting(client):
    """ADM-005/SEC-006: exports beyond the hourly per-admin limit get 429 and no data."""
    case = ModerationCaseFactory()
    case.report.details = "SECRET-REPORT-DETAILS"
    case.report.save(update_fields=["details"])
    super_admin = SuperAdminFactory()
    verify_mfa(client, super_admin)
    for _ in range(EXPORT_RATE_LIMIT):
        record_audit(actor=super_admin, action="moderation.case.export", obj=case)

    response = client.post(export_url(case), {"purpose": VALID_PURPOSE})

    assert response.status_code == 429
    assert "SECRET-REPORT-DETAILS" not in response.content.decode()
    assert (
        AuditEvent.objects.filter(action="moderation.case.export", actor=super_admin).count()
        == EXPORT_RATE_LIMIT
    )
    assert AuditEvent.objects.filter(
        action="moderation.case.export.denied", actor=super_admin, result="failure"
    ).exists()
