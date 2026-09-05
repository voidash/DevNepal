from datetime import UTC, datetime, timedelta

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.ministries.tests.factories import SuperAdminFactory, UserFactory
from apps.moderation.enums import (
    AppealStatus,
    CaseStatus,
    ModerationAction,
    ReportReason,
)
from apps.moderation.models import ModerationCase, Report
from apps.moderation.services import build_community_health_snapshot
from apps.moderation.tests.factories import ModerationCaseFactory, ReportFactory
from apps.projects.tests.factories import ProjectFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def moderation_urlconf():
    with override_settings(ROOT_URLCONF="apps.moderation.tests.urls"):
        yield


def _set_case_times(case, *, created_at, decided_at=None, **fields):
    Report.objects.filter(pk=case.report_id).update(created_at=created_at)
    ModerationCase.objects.filter(pk=case.pk).update(
        created_at=created_at,
        decided_at=decided_at,
        **fields,
    )
    case.refresh_from_db()
    return case


def _verify_mfa(client, user):
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


@pytest.mark.unit
def test_community_health_snapshot_uses_current_month_routine_aggregates_only():
    """ADM-006/SRS 3.2: community health reports current-month aggregate moderation data."""
    now = datetime(2026, 9, 15, 12, tzinfo=UTC)
    target = ProjectFactory()
    branding_unpublish = ModerationCaseFactory(
        report=ReportFactory(target=target, reason=ReportReason.GOV_BRANDING_MISUSE),
        status=CaseStatus.ACTION_TAKEN,
        action=ModerationAction.UNPUBLISH,
        appeal_status=AppealStatus.OVERTURNED,
        appealed_at=now - timedelta(days=12),
        appeal_decided_at=now - timedelta(days=11),
    )
    _set_case_times(
        branding_unpublish,
        created_at=now - timedelta(days=13),
        decided_at=now - timedelta(days=12),
    )
    branding_warning = ModerationCaseFactory(
        report=ReportFactory(target=target, reason=ReportReason.GOV_BRANDING_MISUSE),
        status=CaseStatus.ACTION_TAKEN,
        action=ModerationAction.WARNING,
    )
    _set_case_times(
        branding_warning,
        created_at=now - timedelta(days=10),
        decided_at=now - timedelta(days=7),
    )
    open_case = ModerationCaseFactory(
        report=ReportFactory(target=target, reason=ReportReason.SPAM),
        status=CaseStatus.NEW,
    )
    _set_case_times(open_case, created_at=now - timedelta(days=2))
    security_case = ModerationCaseFactory(
        report=ReportFactory(reason=ReportReason.SECURITY_CONCERN),
        status=CaseStatus.ESCALATED,
    )
    _set_case_times(security_case, created_at=now - timedelta(days=1))
    previous_month_case = ModerationCaseFactory(
        report=ReportFactory(reason=ReportReason.HARASSMENT),
        status=CaseStatus.ACTION_TAKEN,
        action=ModerationAction.WARNING,
    )
    _set_case_times(
        previous_month_case,
        created_at=now - timedelta(days=20),
        decided_at=now - timedelta(days=19),
    )

    health = build_community_health_snapshot(now=now)

    assert health["report_count"] == 4
    assert health["routine_case_count"] == 3
    assert health["security_report_count"] == 1
    assert health["decision_count"] == 2
    assert health["median_decision_hours"] == 48
    assert health["sla_met_count"] == 1
    assert health["sla_met_percent"] == 50
    assert health["appeal_count"] == 1
    assert health["overturned_appeal_count"] == 1
    assert health["repeat_subject_count"] == 1
    assert health["reason_rows"] == [
        {
            "reason": ReportReason.GOV_BRANDING_MISUSE.value,
            "label": "Misleading government branding",
            "case_count": 2,
            "outcomes": [
                {
                    "action": ModerationAction.UNPUBLISH.value,
                    "label": "Unpublish",
                    "count": 1,
                },
                {"action": ModerationAction.WARNING.value, "label": "Warning", "count": 1},
            ],
            "appeal_count": 1,
            "overturned_appeal_count": 1,
        },
        {
            "reason": ReportReason.SPAM.value,
            "label": "Spam",
            "case_count": 1,
            "outcomes": [],
            "appeal_count": 0,
            "overturned_appeal_count": 0,
        },
    ]
    assert health["pattern"] == {
        "reason": ReportReason.GOV_BRANDING_MISUSE.value,
        "label": "Misleading government branding",
        "case_count": 2,
        "percent": 67,
    }


@pytest.mark.integration
def test_community_health_requires_verified_super_admin_and_renders_aggregates_only(client):
    """AUTH-005/ADM-006: health is MFA-gated and excludes confidential report data."""
    super_admin = SuperAdminFactory()
    case = ModerationCaseFactory(
        report=ReportFactory(
            reporter=UserFactory(username="confidential-reporter"),
            details="confidential witness account",
            evidence_url="https://private.example/evidence",
            reason=ReportReason.SPAM,
        ),
        status=CaseStatus.ACTION_TAKEN,
        action=ModerationAction.WARNING,
    )
    _set_case_times(
        case,
        created_at=timezone.now() - timedelta(hours=12),
        decided_at=timezone.now() - timedelta(hours=2),
    )
    client.force_login(super_admin)

    unverified = client.get(reverse("moderation:community_health"))

    assert unverified.status_code == 302
    assert unverified.url == reverse("accounts:mfa_setup")

    _verify_mfa(client, super_admin)
    verified = client.get(reverse("moderation:community_health"))
    rendered = verified.content.decode()

    assert verified.status_code == 200
    assert verified.context["health"]["routine_case_count"] == 1
    assert "Community health" in rendered
    assert "confidential-reporter" not in rendered
    assert "confidential witness account" not in rendered
    assert "private.example/evidence" not in rendered


@pytest.mark.integration
def test_community_health_denies_members(client):
    """ADM-006: members cannot access PMO community-health aggregates."""
    client.force_login(UserFactory())

    response = client.get(reverse("moderation:community_health"))

    assert response.status_code == 403
