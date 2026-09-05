import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.audit.models import AuditEvent
from apps.contributions.enums import VerificationStatus
from apps.contributions.services import place_on_hold
from apps.contributions.tests.factories import ContributionRecordFactory
from apps.ministries.tests.factories import SuperAdminFactory, UserFactory
from apps.recognition.enums import CorrectionKind, CorrectionStatus
from apps.recognition.models import RecognitionCorrection
from apps.recognition.services import (
    CorrectionAuthorizationError,
    CorrectionStateConflictError,
    appeal_correction,
    apply_correction,
    resolve_correction_appeal,
)
from apps.recognition.tests.factories import ContributionScoreFactory

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
    assert client.post(reverse("accounts:mfa_setup"), {"token": token}).status_code == 302


def test_super_admin_consolidates_scores_with_a_reason_audit_and_member_notice():
    """REC-005/BR-010/ADM-007: a reasoned correction preserves the original score history."""
    admin = SuperAdminFactory()
    member = UserFactory()
    first = ContributionScoreFactory(
        contribution=ContributionRecordFactory(
            contributor=member, status=VerificationStatus.ACCEPTED
        ),
        points=8,
    )
    second = ContributionScoreFactory(
        contribution=ContributionRecordFactory(
            contributor=member, status=VerificationStatus.ACCEPTED
        ),
        points=8,
        policy=first.policy,
    )

    correction = apply_correction(
        admin,
        kind=CorrectionKind.CONSOLIDATE,
        contributions=[first.contribution, second.contribution],
        reason="duplicate_trivial_batch",
        basis="Maintainer statement confirms one unit of work.",
        member_note="The two records now appear as one verified contribution.",
        adjusted_points=5,
    )

    first.refresh_from_db()
    second.refresh_from_db()
    assert correction.status == CorrectionStatus.APPLIED
    assert correction.recipient == member
    assert first.points == 5
    assert second.reversed_at is not None
    assert correction.before_snapshot["scores"][0]["points"] == 8
    assert correction.after_snapshot["scores"][0]["points"] == 5
    assert correction.appeal_due_at > timezone.now()
    assert AuditEvent.objects.filter(
        action="recognition.correction.applied", object_id=str(correction.pk)
    ).exists()


def test_member_can_appeal_own_correction_and_different_admin_can_restore_exact_snapshot():
    """REC-005/ADM-007/BR-010: an affected member appeals and a privileged review restores it."""
    first_admin = SuperAdminFactory()
    reviewer = SuperAdminFactory()
    member = UserFactory()
    score = ContributionScoreFactory(
        contribution=ContributionRecordFactory(
            contributor=member, status=VerificationStatus.ACCEPTED
        ),
        points=12,
    )
    correction = apply_correction(
        first_admin,
        kind=CorrectionKind.ADJUST_SCORE,
        contributions=[score.contribution],
        reason="evidence_reassessment",
        basis="The evidence was rechecked.",
        member_note="Your score was adjusted after evidence review.",
        adjusted_points=3,
    )

    appeal = appeal_correction(member, correction, "The supporting evidence was misread.")
    resolved = resolve_correction_appeal(
        reviewer,
        correction,
        outcome=CorrectionStatus.OVERTURNED,
        reason="Evidence supports the original score.",
    )

    score.refresh_from_db()
    appeal.refresh_from_db()
    assert resolved.status == CorrectionStatus.OVERTURNED
    assert appeal.status == CorrectionStatus.OVERTURNED
    assert score.points == 12
    assert AuditEvent.objects.filter(
        action="recognition.correction.appeal_overturned", object_id=str(correction.pk)
    ).exists()


def test_member_cannot_appeal_someone_elses_correction_and_denial_is_audited():
    """ADM-007/SEC-005: correction appeals never disclose or mutate another member's record."""
    admin = SuperAdminFactory()
    member = UserFactory()
    outsider = UserFactory()
    score = ContributionScoreFactory(
        contribution=ContributionRecordFactory(
            contributor=member, status=VerificationStatus.ACCEPTED
        )
    )
    correction = apply_correction(
        admin,
        kind=CorrectionKind.ADJUST_SCORE,
        contributions=[score.contribution],
        reason="evidence_reassessment",
        basis="Evidence basis.",
        member_note="A correction was applied.",
        adjusted_points=1,
    )

    with pytest.raises(CorrectionAuthorizationError):
        appeal_correction(outsider, correction, "Not mine")

    assert AuditEvent.objects.filter(
        action="recognition.correction.appeal.denied", object_id=str(correction.pk)
    ).exists()


def test_overturn_refuses_to_clobber_a_later_recognition_change():
    """REC-005/SEC-008: an appeal cannot restore a snapshot over a newer score decision."""
    first_admin = SuperAdminFactory()
    reviewer = SuperAdminFactory()
    member = UserFactory()
    score = ContributionScoreFactory(
        contribution=ContributionRecordFactory(
            contributor=member, status=VerificationStatus.ACCEPTED
        ),
        points=12,
    )
    correction = apply_correction(
        first_admin,
        kind=CorrectionKind.ADJUST_SCORE,
        contributions=[score.contribution],
        reason="score_calculation_error",
        basis="A calculation was corrected.",
        member_note="Your score was corrected.",
        adjusted_points=3,
    )
    appeal_correction(member, correction, "Please reconsider the calculation.")
    score.points = 7
    score.save(update_fields=["points"])

    with pytest.raises(CorrectionStateConflictError, match="changed after"):
        resolve_correction_appeal(
            reviewer,
            correction,
            outcome=CorrectionStatus.OVERTURNED,
            reason="The later score needs a separate review.",
        )

    score.refresh_from_db()
    assert score.points == 7
    assert AuditEvent.objects.filter(
        action="recognition.correction.appeal.restore.denied", object_id=str(correction.pk)
    ).exists()


def test_release_held_correction_can_be_appealed_and_restores_a_safe_hold():
    """D4.3/REC-005/ADM-007: a release-held correction is safely reversible."""
    first_admin = SuperAdminFactory()
    reviewer = SuperAdminFactory()
    member = UserFactory()
    contribution = ContributionRecordFactory(
        contributor=member,
        status=VerificationStatus.CANDIDATE,
    )
    place_on_hold(first_admin, contribution, "Potential duplicate evidence")
    contribution.refresh_from_db()

    correction = apply_correction(
        first_admin,
        kind=CorrectionKind.RELEASE_HELD,
        contributions=[contribution],
        reason="hold_resolved",
        basis="The duplicate check was resolved.",
        member_note="Your held contribution returned to the review queue.",
    )
    contribution.refresh_from_db()
    assert contribution.hold_active is False
    assert correction.after_snapshot["records"][0]["hold_active"] is False

    appeal_correction(member, correction, "The record should stay on hold.")
    resolve_correction_appeal(
        reviewer,
        correction,
        outcome=CorrectionStatus.OVERTURNED,
        reason="The anomaly remains unresolved.",
    )

    contribution.refresh_from_db()
    assert contribution.hold_active is True


def test_correction_views_enforce_owner_and_verified_super_admin(client):
    """AUTH-005/ADM-007: correction screens separate member history from privileged review."""
    admin = SuperAdminFactory()
    member = UserFactory()
    outsider = UserFactory()
    score = ContributionScoreFactory(
        contribution=ContributionRecordFactory(
            contributor=member, status=VerificationStatus.ACCEPTED
        )
    )
    correction = apply_correction(
        admin,
        kind=CorrectionKind.ADJUST_SCORE,
        contributions=[score.contribution],
        reason="evidence_reassessment",
        basis="Evidence basis.",
        member_note="A correction was applied.",
        adjusted_points=1,
    )

    client.force_login(outsider)
    hidden = client.get(reverse("recognition:correction_appeal", args=[correction.pk]))
    assert hidden.status_code == 404

    client.force_login(member)
    own = client.get(reverse("recognition:correction_appeal", args=[correction.pk]))
    assert own.status_code == 200

    unverified = SuperAdminFactory()
    unverified.otp_device = None
    unverified.is_verified = lambda: False
    client.force_login(unverified)
    gated = client.get(reverse("recognition:correction_create"))
    assert gated.status_code == 302
    assert gated.url == reverse("accounts:mfa_setup")

    verify_mfa(client, admin)
    review = client.get(reverse("recognition:correction_detail", args=[correction.pk]))
    assert review.status_code == 200


def test_correction_form_applies_adjustment_from_super_admin_screen(client):
    """REC-005/ADM-007: the D4.3 correction form applies a scoped score adjustment."""
    admin = SuperAdminFactory()
    member = UserFactory()
    score = ContributionScoreFactory(
        contribution=ContributionRecordFactory(
            contributor=member, status=VerificationStatus.ACCEPTED
        ),
        points=9,
    )
    verify_mfa(client, admin)

    response = client.post(
        reverse("recognition:correction_create"),
        {
            "kind": CorrectionKind.ADJUST_SCORE,
            "contribution_ids": str(score.contribution_id),
            "reason": "evidence_reassessment",
            "basis": "Maintainer evidence review.",
            "member_note": "Your score was corrected after review.",
            "adjusted_points": 4,
        },
    )

    score.refresh_from_db()
    assert response.status_code == 302
    assert score.points == 4
    assert RecognitionCorrection.objects.filter(recipient=member).exists()
