import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.accounts.models import MemberProfile
from apps.audit.models import AuditEvent
from apps.contributions.enums import VerificationStatus
from apps.contributions.tests.factories import ContributionRecordFactory
from apps.ministries.tests.factories import SuperAdminFactory, UserFactory
from apps.recognition.services import activate_policy
from apps.recognition.tests.factories import BadgeAwardFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def recognition_urlconf():
    with override_settings(ROOT_URLCONF="apps.recognition.tests.urls"):
        yield


def verify_mfa(client, user):
    client.force_login(user)
    device = TOTPDevice.objects.get(user=user)
    token = totp(
        device.bin_key,
        step=device.step,
        t0=device.t0,
        digits=device.digits,
        drift=device.drift,
    )
    response = client.post(reverse("accounts:mfa_setup"), {"token": token})
    assert response.status_code == 302


def accepted_batch(member, project, contribution_type, count, *, title_prefix):
    return [
        ContributionRecordFactory(
            project=project,
            contributor=member,
            contribution_type=contribution_type,
            title=f"{title_prefix} {index}",
            status=VerificationStatus.ACCEPTED,
            verified_at=timezone.now(),
        )
        for index in range(count)
    ]


@pytest.mark.integration
def test_anomaly_review_lists_members_exceeding_policy_velocity_caps(client):
    """REC-006: members whose accepted-contribution velocity exceeds policy caps are listed."""
    super_admin = SuperAdminFactory()
    activate_policy(
        super_admin,
        {
            "standard": 3,
            "anomaly_review": {"velocity_threshold": 2, "velocity_window_days": 7},
        },
    )
    fast = UserFactory()
    slow = UserFactory()
    project = ContributionRecordFactory().project
    contribution_type = ContributionRecordFactory().contribution_type
    accepted_batch(fast, project, contribution_type, 3, title_prefix="Fast task")
    accepted_batch(slow, project, contribution_type, 1, title_prefix="Slow task")
    verify_mfa(client, super_admin)

    response = client.get(reverse("recognition:anomaly_review"))

    rows = {row["contributor__username"]: row for row in response.context["rows"]}
    assert response.status_code == 200
    assert fast.username in rows
    assert slow.username not in rows
    assert rows[fast.username]["accepted_count"] == 3
    assert response.context["velocity_threshold"] == 2


@pytest.mark.integration
def test_anomaly_review_flags_duplicate_title_patterns(client):
    """REC-006: members resubmitting identical accepted titles are flagged for review."""
    super_admin = SuperAdminFactory()
    activate_policy(super_admin, {"standard": 3})
    member = UserFactory()
    project = ContributionRecordFactory().project
    contribution_type = ContributionRecordFactory().contribution_type
    accepted_batch(member, project, contribution_type, 1, title_prefix="Same task")
    ContributionRecordFactory(
        project=project,
        contributor=member,
        contribution_type=contribution_type,
        title="Same task 0",
        status=VerificationStatus.ACCEPTED,
        verified_at=timezone.now(),
    )
    ContributionRecordFactory(
        project=project,
        contributor=UserFactory(),
        contribution_type=contribution_type,
        title="Different task",
        status=VerificationStatus.ACCEPTED,
        verified_at=timezone.now(),
    )
    verify_mfa(client, super_admin)

    response = client.get(reverse("recognition:anomaly_review"))

    rows = {row["contributor__username"]: row for row in response.context["rows"]}
    assert response.status_code == 200
    assert member.username in rows
    assert rows[member.username]["duplicate_titles"] == 1
    assert rows[member.username]["velocity_flag"] is False


@pytest.mark.integration
def test_anomaly_review_uses_conservative_defaults_without_policy_rules(client):
    """REC-006: without policy anomaly rules the review falls back to conservative caps."""
    super_admin = SuperAdminFactory()
    activate_policy(super_admin, {"standard": 3})
    heavy = UserFactory()
    light = UserFactory()
    project = ContributionRecordFactory().project
    contribution_type = ContributionRecordFactory().contribution_type
    accepted_batch(heavy, project, contribution_type, 21, title_prefix="Heavy task")
    accepted_batch(light, project, contribution_type, 1, title_prefix="Light task")
    verify_mfa(client, super_admin)

    response = client.get(reverse("recognition:anomaly_review"))

    rows = {row["contributor__username"]: row for row in response.context["rows"]}
    assert response.status_code == 200
    assert heavy.username in rows
    assert light.username not in rows
    assert response.context["velocity_threshold"] >= 20


@pytest.mark.integration
def test_anomaly_review_is_read_only_and_mfa_gated(client):
    """REC-006/AUTH-005: anomaly review is a read-only verified Super Admin surface."""
    super_admin = SuperAdminFactory()
    member = UserFactory()
    ContributionRecordFactory(
        contributor=member,
        status=VerificationStatus.ACCEPTED,
        verified_at=timezone.now(),
    )
    award = BadgeAwardFactory(recipient=member)
    url = reverse("recognition:anomaly_review")
    unverified_admin = SuperAdminFactory()
    unverified_admin.otp_device = None
    unverified_admin.is_verified = lambda: False
    client.force_login(unverified_admin)
    audit_count = AuditEvent.objects.count()

    unverified_response = client.get(url)

    assert unverified_response.status_code == 302
    assert unverified_response.url == reverse("accounts:mfa_setup")

    client.force_login(member)
    member_response = client.get(url)

    assert member_response.status_code == 403

    verify_mfa(client, super_admin)
    review_response = client.get(url)

    assert review_response.status_code == 200
    assert AuditEvent.objects.count() == audit_count
    assert award.status == "active"
    assert MemberProfile.objects.filter(user=member, leaderboard_opt_out=True).exists() is False


@pytest.mark.integration
def test_anomaly_review_rows_link_to_member_contribution_history(client):
    """REC-006: each flagged row links to the member's contribution history."""
    super_admin = SuperAdminFactory()
    member = UserFactory()
    project = ContributionRecordFactory().project
    contribution_type = ContributionRecordFactory().contribution_type
    accepted_batch(member, project, contribution_type, 2, title_prefix="Repeated task")
    ContributionRecordFactory(
        project=project,
        contributor=member,
        contribution_type=contribution_type,
        title="Repeated task 0",
        status=VerificationStatus.ACCEPTED,
        verified_at=timezone.now(),
    )
    verify_mfa(client, super_admin)

    response = client.get(reverse("recognition:anomaly_review"))

    profile_path = reverse("accounts:public_profile", args=[member.username])
    assert response.status_code == 200
    assert profile_path.encode() in response.content
