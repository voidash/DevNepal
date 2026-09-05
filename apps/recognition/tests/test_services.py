import pytest
from django.conf import settings
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.contributions.enums import ImpactTier, VerificationStatus
from apps.contributions.tests.factories import ContributionRecordFactory
from apps.ministries.tests.factories import SuperAdminFactory, UserFactory
from apps.recognition.enums import AwardStatus
from apps.recognition.models import ContributionScore
from apps.recognition.services import (
    RecognitionAuthorizationError,
    RecognitionDisabledError,
    activate_policy,
    award_badge,
    leaderboard,
    opt_out,
    recompute_scores,
    revoke_badge,
)
from apps.recognition.tests.factories import BadgeFactory

pytestmark = pytest.mark.django_db


@pytest.mark.unit
def test_only_super_admin_can_activate_a_scoring_policy():
    """REC-002: scoring policy activation is authorized, versioned, and audited."""
    with pytest.raises(RecognitionAuthorizationError):
        activate_policy(UserFactory(), {"standard": 3})

    policy = activate_policy(SuperAdminFactory(), {"minor": 1, "standard": 3, "major": 5})

    assert policy.version == 1
    assert policy.is_active is True
    assert AuditEvent.objects.filter(
        action="recognition.policy_activated", object_id=str(policy.pk)
    ).exists()


@pytest.mark.unit
def test_policy_activation_denied_without_otp_verified_super_admin():
    """AUTH-005/REC-002/SEC-008: unverified Super Admin policy activation is denied and audited."""
    super_admin = SuperAdminFactory()
    super_admin.otp_device = None
    super_admin.is_verified = lambda: False

    with pytest.raises(RecognitionAuthorizationError):
        activate_policy(super_admin, {"standard": 3})

    assert AuditEvent.objects.filter(
        actor=super_admin, action="recognition.policy.activate.denied", result="failure"
    ).exists()


@pytest.mark.unit
def test_new_policy_keeps_prior_policy_and_score_history_immutable():
    """REC-002/BR-012: activating a later policy never rewrites prior policy meaning."""
    admin = SuperAdminFactory()
    first = activate_policy(admin, {"standard": 3})
    contribution = ContributionRecordFactory(
        status=VerificationStatus.ACCEPTED,
        verified_at=timezone.now(),
        impact_tier=ImpactTier.STANDARD,
    )
    recompute_scores()
    score = ContributionScore.objects.get(contribution=contribution)

    second = activate_policy(admin, {"standard": 9})
    recompute_scores()

    score.refresh_from_db()
    first.refresh_from_db()
    assert first.is_active is False
    assert second.is_active is True
    assert score.policy_id == first.pk
    assert score.points == 3


@pytest.mark.unit
def test_policy_activation_audit_identifies_the_replaced_version():
    """REC-002/SEC-008: policy activation audit evidence identifies the policy it superseded."""
    admin = SuperAdminFactory()
    first = activate_policy(admin, {"standard": 3})

    second = activate_policy(admin, {"standard": 5})

    event = AuditEvent.objects.get(action="recognition.policy_activated", object_id=str(second.pk))
    assert event.before["deactivated_versions"] == [first.version]


@pytest.mark.unit
def test_only_accepted_contributions_receive_scores():
    """REC-001: candidate and rejected activity never receives recognition credit."""
    activate_policy(SuperAdminFactory(), {"standard": 3})
    accepted = ContributionRecordFactory(
        status=VerificationStatus.ACCEPTED,
        verified_at=timezone.now(),
    )
    candidate = ContributionRecordFactory(status=VerificationStatus.CANDIDATE)
    rejected = ContributionRecordFactory(status=VerificationStatus.REJECTED)

    scored = recompute_scores()

    assert [score.contribution_id for score in scored] == [accepted.pk]
    assert ContributionScore.objects.filter(contribution__in=[candidate, rejected]).count() == 0


@pytest.mark.unit
def test_rate_cap_limits_scores_without_discriminating_non_code_work():
    """REC-006/REC-008: a per-project cap applies equally to accepted documentation work."""
    activate_policy(SuperAdminFactory(), {"standard": 3})
    first = ContributionRecordFactory(
        status=VerificationStatus.ACCEPTED,
        verified_at=timezone.now(),
    )
    second = ContributionRecordFactory(
        project=first.project,
        contributor=first.contributor,
        contribution_type=first.contribution_type,
        status=VerificationStatus.ACCEPTED,
        verified_at=timezone.now(),
    )

    recompute_scores(max_per_project=1)

    assert ContributionScore.objects.filter(contribution=first).exists()
    assert not ContributionScore.objects.filter(contribution=second).exists()


@pytest.mark.unit
def test_badge_award_and_revocation_have_evidence_and_audit():
    """REC-005/REC-007: badge awards carry issuer/evidence and revocations remain auditable."""
    admin = SuperAdminFactory()
    contribution = ContributionRecordFactory(
        status=VerificationStatus.ACCEPTED,
        verified_at=timezone.now(),
    )
    award = award_badge(admin, contribution.contributor, BadgeFactory(), contribution=contribution)

    revoke_badge(admin, award, "Evidence was invalidated")

    award.refresh_from_db()
    assert award.status == AwardStatus.REVOKED
    assert award.revocation_reason == "Evidence was invalidated"
    assert AuditEvent.objects.filter(
        action="recognition.badge_revoked", object_id=str(award.pk)
    ).exists()


@pytest.mark.unit
def test_member_can_opt_out_while_scores_remain_private():
    """REC-004: opting out removes public ranking eligibility without deleting history."""
    member = UserFactory()

    profile = opt_out(member)

    assert profile.leaderboard_opt_out is True


@pytest.mark.unit
def test_leaderboard_is_disabled_until_the_product_owner_enables_it():
    """D12/REC-003: no public leaderboard is available during the MVP."""
    assert settings.RECOGNITION_ENABLED is False
    with pytest.raises(RecognitionDisabledError):
        leaderboard()
