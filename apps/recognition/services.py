from collections import defaultdict
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Count, F, Q, Sum
from django.utils import timezone

from apps.accounts.models import MemberProfile
from apps.accounts.services import require_privileged_mfa
from apps.audit.services import record_audit
from apps.contributions.enums import VerificationStatus
from apps.contributions.models import ContributionRecord
from apps.recognition.enums import AwardStatus, CorrectionKind, CorrectionReason, CorrectionStatus
from apps.recognition.models import (
    Badge,
    BadgeAward,
    ContributionScore,
    RecognitionCorrection,
    ScoringPolicy,
)
from apps.taxonomy.fields import normalize_nfc

DEFAULT_ANOMALY_WINDOW_DAYS = 7
DEFAULT_VELOCITY_THRESHOLD = 20
DEFAULT_DUPLICATE_THRESHOLD = 2


class RecognitionError(Exception):
    """Recognition policy or score processing failed."""


class RecognitionAuthorizationError(RecognitionError):
    """The actor is not allowed to change recognition state."""


class RecognitionDisabledError(RecognitionError):
    """A public recognition view was called while the feature is disabled."""


class CorrectionError(RecognitionError):
    """A recognition correction or appeal could not be completed (REC-005, ADM-007)."""


class CorrectionAuthorizationError(CorrectionError):
    """The actor cannot submit or resolve this correction appeal (SEC-005)."""


class CorrectionStateConflictError(CorrectionError):
    """The recognition state changed after the correction and cannot safely be restored."""


def _require_super_admin(actor, *, action: str, obj=None) -> None:
    if not actor or not actor.is_active or not actor.is_superuser:
        record_audit(actor=actor, action=f"{action}.denied", obj=obj, result="failure")
        raise RecognitionAuthorizationError("a Super Admin is required")
    require_privileged_mfa(actor, action=action, obj=obj, error_type=RecognitionAuthorizationError)


def activate_policy(actor, rules: dict, *, document_url: str = "") -> ScoringPolicy:
    """REC-002/BR-012: activate a new immutable scoring-policy version."""
    _require_super_admin(actor, action="recognition.policy.activate")
    return _activate_policy(actor, rules, document_url=document_url)


@transaction.atomic
def create_badge(actor, **attributes) -> Badge:
    """REC-007: create a documented badge through a verified Super Admin action."""
    _require_super_admin(actor, action="recognition.badge.create")
    badge = Badge.objects.create(**attributes)
    record_audit(
        actor=actor,
        action="recognition.badge_created",
        obj=badge,
        after={"slug": badge.slug, "criteria_version": badge.criteria_version},
    )
    return badge


@transaction.atomic
def update_badge(actor, badge: Badge, **attributes) -> Badge:
    """REC-007: update badge criteria with attributable audit history."""
    _require_super_admin(actor, action="recognition.badge.update", obj=badge)
    before = {field: getattr(badge, field) for field in attributes}
    changed = {field: value for field, value in attributes.items() if before[field] != value}
    if not changed:
        return badge
    for field, value in changed.items():
        setattr(badge, field, value)
    badge.save()
    record_audit(
        actor=actor,
        action="recognition.badge_updated",
        obj=badge,
        before={field: _audit_value(before[field]) for field in changed},
        after={field: _audit_value(getattr(badge, field)) for field in changed},
    )
    return badge


def _audit_value(value):
    return getattr(value, "name", value)


@transaction.atomic
def _activate_policy(actor, rules: dict, *, document_url: str = "") -> ScoringPolicy:
    _validate_policy_rules(rules)
    previous = ScoringPolicy.objects.filter(is_active=True)
    previous_versions = list(previous.values_list("version", flat=True))
    previous.update(is_active=False)
    latest_version = (
        ScoringPolicy.objects.order_by("-version").values_list("version", flat=True).first()
    )
    version = (latest_version or 0) + 1
    policy = ScoringPolicy.objects.create(
        version=version,
        rules=rules,
        document_url=document_url,
        approved_by=actor,
        activated_at=timezone.now(),
        is_active=True,
    )
    record_audit(
        actor=actor,
        action="recognition.policy_activated",
        obj=policy,
        before={"deactivated_versions": previous_versions},
        after={"version": policy.version, "rules": policy.rules},
    )
    return policy


def _active_policy() -> ScoringPolicy:
    policy = ScoringPolicy.objects.filter(is_active=True).first()
    if policy is None:
        raise RecognitionError("no active scoring policy")
    return policy


def _validate_policy_rules(rules: dict) -> None:
    if not isinstance(rules, dict):
        raise RecognitionError("scoring policy rules must be a dictionary")
    badge_rules = rules.get("badges", {})
    if not isinstance(badge_rules, dict):
        raise RecognitionError("badge rules must be a dictionary")
    anomaly_rules = rules.get("anomaly_review", {})
    if not isinstance(anomaly_rules, dict):
        raise RecognitionError("anomaly review rules must be a dictionary")
    for value in anomaly_rules.values():
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise RecognitionError("anomaly review thresholds must be positive integers")
    for impact_tier, points in rules.items():
        if impact_tier not in ("badges", "anomaly_review") and (
            not isinstance(points, int) or isinstance(points, bool) or points < 0
        ):
            raise RecognitionError("scoring policy point values must be non-negative integers")
    for badge_slug, criteria in badge_rules.items():
        if not isinstance(badge_slug, str) or not isinstance(criteria, dict):
            raise RecognitionError("each badge rule requires a slug and criteria dictionary")
        minimum_points = criteria.get("minimum_points")
        if (
            not isinstance(minimum_points, int)
            or isinstance(minimum_points, bool)
            or minimum_points < 1
        ):
            raise RecognitionError("badge minimum_points must be a positive integer")


@transaction.atomic
def evaluate_accepted_contribution(
    contribution: ContributionRecord,
) -> tuple[ContributionScore | None, list[BadgeAward]]:
    """REC-001/REC-002: score one accepted contribution and evaluate active policy badges."""
    if not settings.RECOGNITION_ENABLED:
        return None, []
    if contribution.status != VerificationStatus.ACCEPTED or contribution.contributor_id is None:
        return None, []
    policy = ScoringPolicy.objects.filter(is_active=True).first()
    if policy is None:
        return None, []
    if policy.approved_by is None:
        raise RecognitionError("active scoring policy requires an approving Super Admin")
    _validate_policy_rules(policy.rules)
    points = int(policy.rules.get(contribution.impact_tier, policy.rules.get("default", 0)))
    score, created = ContributionScore.objects.get_or_create(
        contribution=contribution,
        defaults={"policy": policy, "points": max(points, 0)},
    )
    if not created:
        return score, []
    record_audit(
        actor=policy.approved_by,
        action="recognition.contribution_scored",
        obj=score,
        after={
            "contribution_id": contribution.pk,
            "policy_version": policy.version,
            "points": score.points,
        },
    )
    total_points = (
        ContributionScore.objects.filter(
            contribution__contributor_id=contribution.contributor_id,
            contribution__status=VerificationStatus.ACCEPTED,
            policy=policy,
        ).aggregate(total=Sum("points"))["total"]
        or 0
    )
    badge_rules = policy.rules.get("badges", {})
    badges = Badge.objects.filter(slug__in=badge_rules, is_active=True)
    awards = []
    for badge in badges:
        if total_points >= badge_rules[badge.slug]["minimum_points"]:
            awards.append(
                _award_badge(
                    policy.approved_by,
                    contribution.contributor,
                    badge,
                    contribution=contribution,
                )
            )
    return score, awards


@transaction.atomic
def reverse_accepted_contribution(actor, contribution: ContributionRecord, reason: str) -> None:
    """REC-005: reverse recognition derived from an invalidated contribution."""
    score = ContributionScore.objects.filter(contribution=contribution).first()
    if score is not None and score.reversed_at is None:
        score.reversed_at = timezone.now()
        score.reversal_reason = reason
        score.save(update_fields=["reversed_at", "reversal_reason"])
        record_audit(
            actor=actor,
            action="recognition.contribution_score_reversed",
            obj=score,
            before={"reversed_at": None},
            after={"contribution_id": contribution.pk, "reason": reason},
        )
    for award in BadgeAward.objects.filter(
        contribution=contribution, status=AwardStatus.ACTIVE
    ).select_related("badge"):
        _revoke_badge(actor, award, reason)


@transaction.atomic
def recompute_scores(
    *, window_days: int = 90, max_per_project: int = 20
) -> list[ContributionScore]:
    """REC-001/REC-006/D8: score only unscored accepted work inside the rolling window."""
    policy = _active_policy()
    start = timezone.now() - timedelta(days=window_days)
    contributions = (
        ContributionRecord.objects.filter(
            status=VerificationStatus.ACCEPTED,
            contributor__isnull=False,
            verified_at__gte=start,
            score__isnull=True,
        )
        .select_related("contributor")
        .order_by("project_id", "contributor_id", "verified_at", "pk")
    )
    per_project = defaultdict(int)
    scores = []
    for contribution in contributions:
        key = (contribution.project_id, contribution.contributor_id)
        if per_project[key] >= max_per_project:
            continue
        per_project[key] += 1
        points = int(policy.rules.get(contribution.impact_tier, policy.rules.get("default", 0)))
        scores.append(
            ContributionScore.objects.create(
                contribution=contribution,
                policy=policy,
                points=max(points, 0),
            )
        )
    return scores


def award_badge(
    actor, recipient, badge: Badge, *, contribution=None, reason: str = ""
) -> BadgeAward:
    """REC-007: award a documented badge with attributable issuer and evidence."""
    _require_super_admin(actor, action="recognition.badge.award", obj=badge)
    return _award_badge(actor, recipient, badge, contribution=contribution, reason=reason)


@transaction.atomic
def _award_badge(actor, recipient, badge: Badge, *, contribution=None, reason: str = ""):
    if not badge.is_active:
        raise RecognitionError("inactive badges cannot be awarded")
    award, created = BadgeAward.objects.get_or_create(
        badge=badge,
        recipient=recipient,
        status=AwardStatus.ACTIVE,
        defaults={"issuer": actor, "contribution": contribution},
    )
    if created:
        after = {"badge": badge.slug, "contribution_id": getattr(contribution, "pk", None)}
        if reason:
            after["reason"] = reason
        record_audit(
            actor=actor,
            action="recognition.badge_awarded",
            obj=award,
            after=after,
        )
    return award


def revoke_badge(actor, award: BadgeAward, reason: str) -> BadgeAward:
    """REC-005: revoke a badge with a reason and immutable audit evidence."""
    _require_super_admin(actor, action="recognition.badge.revoke", obj=award)
    return _revoke_badge(actor, award, reason)


@transaction.atomic
def _revoke_badge(actor, award: BadgeAward, reason: str) -> BadgeAward:
    if not reason.strip():
        raise RecognitionError("a revocation reason is required")
    if award.status == AwardStatus.REVOKED:
        return award
    award.status = AwardStatus.REVOKED
    award.revocation_reason = reason
    award.revoked_by = actor
    award.revoked_at = timezone.now()
    award.save(update_fields=["status", "revocation_reason", "revoked_by", "revoked_at"])
    record_audit(
        actor=actor,
        action="recognition.badge_revoked",
        obj=award,
        before={"status": AwardStatus.ACTIVE},
        after={"status": AwardStatus.REVOKED, "reason": reason},
    )
    return award


def apply_correction(
    actor,
    *,
    kind: str,
    contributions: list[ContributionRecord],
    reason: str,
    basis: str,
    member_note: str,
    adjusted_points: int | None = None,
) -> RecognitionCorrection:
    """REC-005/BR-010: apply an attributable, reversible recognition correction."""
    _require_super_admin(actor, action="recognition.correction.apply")
    normalized = _validate_correction_input(
        kind=kind,
        contributions=contributions,
        reason=reason,
        basis=basis,
        member_note=member_note,
        adjusted_points=adjusted_points,
    )
    contribution_ids = [contribution.pk for contribution in contributions]
    with transaction.atomic():
        locked_contributions = list(
            ContributionRecord.objects.select_for_update()
            .filter(pk__in=contribution_ids)
            .select_related("contributor")
            .order_by("pk")
        )
        if len(locked_contributions) != len(set(contribution_ids)):
            raise CorrectionError("one or more contribution records no longer exist")
        recipient = _correction_recipient(locked_contributions)
        before_snapshot = _recognition_snapshot(locked_contributions)
        correction = RecognitionCorrection.objects.create(
            recipient=recipient,
            kind=kind,
            reason=normalized["reason"],
            basis=normalized["basis"],
            member_note=normalized["member_note"],
            adjusted_points=normalized["adjusted_points"],
            before_snapshot=before_snapshot,
            applied_by=actor,
            appeal_due_at=timezone.now() + timedelta(days=14),
        )
        correction.contributions.set(locked_contributions)
        _apply_correction_state(
            actor,
            correction,
            locked_contributions,
            adjusted_points=normalized["adjusted_points"],
        )
        for contribution in locked_contributions:
            contribution.refresh_from_db()
        correction.after_snapshot = _recognition_snapshot(locked_contributions)
        correction.save(update_fields=["after_snapshot"])
        record_audit(
            actor=actor,
            action="recognition.correction.applied",
            obj=correction,
            before=before_snapshot,
            after={
                "kind": correction.kind,
                "reason": correction.reason,
                "basis": correction.basis,
                "member_note": correction.member_note,
                "snapshot": correction.after_snapshot,
            },
        )
    return correction


def appeal_correction(
    member, correction: RecognitionCorrection, grounds: str
) -> RecognitionCorrection:
    """ADM-007/BR-010: the affected member can appeal a current recognition correction."""
    grounds = normalize_nfc(str(grounds or "")).strip()
    if not grounds:
        raise CorrectionError("appeal grounds are required")
    if member is None or not member.is_active or correction.recipient_id != member.pk:
        record_audit(
            actor=member,
            action="recognition.correction.appeal.denied",
            obj=correction,
            result="failure",
        )
        raise CorrectionAuthorizationError("only the affected member may appeal this correction")
    now = timezone.now()
    if correction.status != CorrectionStatus.APPLIED or correction.appeal_due_at < now:
        record_audit(
            actor=member,
            action="recognition.correction.appeal.denied",
            obj=correction,
            before={
                "status": correction.status,
                "appeal_due_at": correction.appeal_due_at.isoformat(),
            },
            result="failure",
        )
        raise CorrectionError("this correction is not available for appeal")
    with transaction.atomic():
        locked = RecognitionCorrection.objects.select_for_update().get(pk=correction.pk)
        if locked.status != CorrectionStatus.APPLIED or locked.appeal_due_at < timezone.now():
            raise CorrectionError("this correction is not available for appeal")
        locked.appeal_text = grounds
        locked.appealed_at = timezone.now()
        locked.status = CorrectionStatus.APPEALED
        locked.save(update_fields=["appeal_text", "appealed_at", "status"])
        record_audit(
            actor=member,
            action="recognition.correction.appealed",
            obj=locked,
            before={"status": CorrectionStatus.APPLIED},
            after={"status": CorrectionStatus.APPEALED, "grounds": grounds},
        )
    return locked


def resolve_correction_appeal(
    actor,
    correction: RecognitionCorrection,
    *,
    outcome: str,
    reason: str,
) -> RecognitionCorrection:
    """ADM-007/REC-005: a different MFA-verified Super Admin upholds or overturns an appeal."""
    _require_super_admin(actor, action="recognition.correction.appeal.resolve", obj=correction)
    reason = normalize_nfc(str(reason or "")).strip()
    if outcome not in {CorrectionStatus.UPHELD, CorrectionStatus.OVERTURNED}:
        raise CorrectionError("appeal outcome must be upheld or overturned")
    if not reason:
        raise CorrectionError("appeal resolution requires a reason")
    if correction.applied_by_id == actor.pk:
        record_audit(
            actor=actor,
            action="recognition.correction.appeal.resolve.denied",
            obj=correction,
            result="failure",
        )
        raise CorrectionAuthorizationError("a different Super Admin must review this appeal")
    conflict = False
    no_pending_appeal = False
    with transaction.atomic():
        locked = (
            RecognitionCorrection.objects.select_for_update()
            .select_related("recipient")
            .prefetch_related("contributions")
            .get(pk=correction.pk)
        )
        if locked.status != CorrectionStatus.APPEALED:
            no_pending_appeal = True
        elif outcome == CorrectionStatus.OVERTURNED:
            contributions = list(locked.contributions.select_for_update().order_by("pk"))
            if _recognition_snapshot(contributions) != locked.after_snapshot:
                conflict = True
            else:
                _restore_correction_state(actor, locked, contributions)
        if not conflict:
            locked.status = outcome
            locked.appeal_decided_by = actor
            locked.appeal_decided_at = timezone.now()
            locked.appeal_decision_reason = reason
            locked.save(
                update_fields=[
                    "status",
                    "appeal_decided_by",
                    "appeal_decided_at",
                    "appeal_decision_reason",
                ]
            )
            record_audit(
                actor=actor,
                action=f"recognition.correction.appeal_{outcome}",
                obj=locked,
                before={"status": CorrectionStatus.APPEALED},
                after={"status": outcome, "reason": reason},
            )
    if no_pending_appeal:
        raise CorrectionError("there is no pending correction appeal to resolve")
    if conflict:
        record_audit(
            actor=actor,
            action="recognition.correction.appeal.restore.denied",
            obj=correction,
            result="failure",
        )
        raise CorrectionStateConflictError("recognition state changed after this correction")
    return locked


def _validate_correction_input(
    *,
    kind: str,
    contributions: list[ContributionRecord],
    reason: str,
    basis: str,
    member_note: str,
    adjusted_points: int | None,
) -> dict:
    if kind not in CorrectionKind.values:
        raise CorrectionError("choose a valid correction type")
    if not contributions or any(contribution.pk is None for contribution in contributions):
        raise CorrectionError("select one or more saved contribution records")
    if len({contribution.pk for contribution in contributions}) != len(contributions):
        raise CorrectionError("each contribution can be selected only once")
    if not all(contribution.contributor_id for contribution in contributions):
        raise CorrectionError("selected contributions need an attributed member")
    if len({contribution.contributor_id for contribution in contributions}) != 1:
        raise CorrectionError("a correction can affect only one member at a time")
    values = {
        "reason": normalize_nfc(str(reason or "")).strip(),
        "basis": normalize_nfc(str(basis or "")).strip(),
        "member_note": normalize_nfc(str(member_note or "")).strip(),
        "adjusted_points": adjusted_points,
    }
    if not values["reason"] or not values["basis"] or not values["member_note"]:
        raise CorrectionError("reason, basis, and member notice are required")
    if values["reason"] not in CorrectionReason.values:
        raise CorrectionError("choose a defined correction reason")
    if kind == CorrectionKind.CONSOLIDATE and len(contributions) < 2:
        raise CorrectionError("consolidation requires at least two contribution records")
    if kind == CorrectionKind.ADJUST_SCORE and len(contributions) != 1:
        raise CorrectionError("score adjustment requires exactly one contribution record")
    if kind in {CorrectionKind.CONSOLIDATE, CorrectionKind.ADJUST_SCORE} and (
        not isinstance(adjusted_points, int)
        or isinstance(adjusted_points, bool)
        or adjusted_points < 0
    ):
        raise CorrectionError("the corrected score must be a non-negative whole number")
    if kind not in {CorrectionKind.CONSOLIDATE, CorrectionKind.ADJUST_SCORE}:
        values["adjusted_points"] = None
    return values


def _correction_recipient(contributions: list[ContributionRecord]):
    recipient = contributions[0].contributor
    if recipient is None or any(
        contribution.contributor_id != recipient.pk for contribution in contributions
    ):
        raise CorrectionError("a correction can affect only one attributed member")
    return recipient


def _apply_correction_state(
    actor,
    correction: RecognitionCorrection,
    contributions: list[ContributionRecord],
    *,
    adjusted_points: int | None,
) -> None:
    if correction.kind == CorrectionKind.RELEASE_HELD:
        from apps.contributions.services import ContributionServiceError, release_hold

        if any(
            not contribution.hold_active or contribution.hold_response
            for contribution in contributions
        ):
            raise CorrectionError(
                "only unanswered active holds can be released as a reversible correction"
            )
        try:
            for contribution in contributions:
                release_hold(actor, contribution, correction.reason)
        except ContributionServiceError as error:
            raise CorrectionError(str(error)) from error
        return
    scores = _locked_scores(contributions)
    if len(scores) != len(contributions):
        raise CorrectionError("every selected contribution requires an existing recognition score")
    if any(score.reversed_at is not None for score in scores):
        raise CorrectionError("a correction can only change active recognition scores")
    if correction.kind == CorrectionKind.ADJUST_SCORE:
        scores[0].points = adjusted_points
        scores[0].save(update_fields=["points"])
        return
    if correction.kind == CorrectionKind.CONSOLIDATE:
        scores[0].points = adjusted_points
        scores[0].save(update_fields=["points"])
        scores = scores[1:]
    for score in scores:
        _reverse_score(actor, score, correction.reason)


def _restore_correction_state(
    actor,
    correction: RecognitionCorrection,
    contributions: list[ContributionRecord],
) -> None:
    if correction.kind == CorrectionKind.RELEASE_HELD:
        from apps.contributions.services import ContributionServiceError, place_on_hold

        try:
            for contribution in contributions:
                place_on_hold(actor, contribution, correction.reason)
        except ContributionServiceError as error:
            raise CorrectionStateConflictError(str(error)) from error
        return
    before_scores = {row["id"]: row for row in correction.before_snapshot["scores"]}
    for score in _locked_scores(contributions):
        row = before_scores.get(score.pk)
        if row is None:
            raise CorrectionStateConflictError(
                "a score is missing from the original correction snapshot"
            )
        score.points = row["points"]
        score.reversed_at = _parse_snapshot_time(row["reversed_at"])
        score.reversal_reason = row["reversal_reason"]
        score.save(update_fields=["points", "reversed_at", "reversal_reason"])
    before_awards = {row["id"]: row for row in correction.before_snapshot["awards"]}
    for award in BadgeAward.objects.select_for_update().filter(contribution__in=contributions):
        row = before_awards.get(award.pk)
        if row is None:
            raise CorrectionStateConflictError(
                "a badge award is missing from the original correction snapshot"
            )
        award.status = row["status"]
        award.revocation_reason = row["revocation_reason"]
        award.revoked_by_id = row["revoked_by_id"]
        award.revoked_at = _parse_snapshot_time(row["revoked_at"])
        award.save(update_fields=["status", "revocation_reason", "revoked_by", "revoked_at"])


def _locked_scores(contributions: list[ContributionRecord]) -> list[ContributionScore]:
    score_by_contribution = {
        score.contribution_id: score
        for score in ContributionScore.objects.select_for_update()
        .filter(contribution__in=contributions)
        .order_by("contribution_id")
    }
    return [
        score_by_contribution[contribution.pk]
        for contribution in contributions
        if contribution.pk in score_by_contribution
    ]


def _reverse_score(actor, score: ContributionScore, reason: str) -> None:
    if score.reversed_at is None:
        score.reversed_at = timezone.now()
        score.reversal_reason = reason
        score.save(update_fields=["reversed_at", "reversal_reason"])
    for award in BadgeAward.objects.select_for_update().filter(
        contribution=score.contribution, status=AwardStatus.ACTIVE
    ):
        award.status = AwardStatus.REVOKED
        award.revocation_reason = reason
        award.revoked_by = actor
        award.revoked_at = timezone.now()
        award.save(update_fields=["status", "revocation_reason", "revoked_by", "revoked_at"])


def _recognition_snapshot(contributions: list[ContributionRecord]) -> dict:
    contribution_ids = [contribution.pk for contribution in contributions]
    scores = ContributionScore.objects.filter(contribution_id__in=contribution_ids).order_by(
        "contribution_id"
    )
    awards = BadgeAward.objects.filter(contribution_id__in=contribution_ids).order_by("pk")
    return {
        "records": [
            {
                "id": contribution.pk,
                "hold_active": contribution.hold_active,
                "held_from_status": contribution.held_from_status,
            }
            for contribution in sorted(contributions, key=lambda contribution: contribution.pk)
        ],
        "scores": [
            {
                "id": score.pk,
                "contribution_id": score.contribution_id,
                "points": score.points,
                "reversed_at": score.reversed_at.isoformat() if score.reversed_at else None,
                "reversal_reason": score.reversal_reason,
            }
            for score in scores
        ],
        "awards": [
            {
                "id": award.pk,
                "contribution_id": award.contribution_id,
                "status": award.status,
                "revocation_reason": award.revocation_reason,
                "revoked_by_id": award.revoked_by_id,
                "revoked_at": award.revoked_at.isoformat() if award.revoked_at else None,
            }
            for award in awards
        ],
    }


def _parse_snapshot_time(value):
    if value is None:
        return None
    return datetime.fromisoformat(value)


def opt_out(member) -> MemberProfile:
    """REC-004: keep history but opt the member out of public ranking displays."""
    profile, _ = MemberProfile.objects.get_or_create(user=member)
    profile.leaderboard_opt_out = True
    profile.save(update_fields=["leaderboard_opt_out"])
    return profile


def leaderboard(*, window_days: int = 90):
    """D12: public rankings remain unavailable until policy validation completes."""
    if not settings.RECOGNITION_ENABLED:
        raise RecognitionDisabledError("public leaderboard is disabled")
    return (
        ContributionScore.objects.filter(
            scored_at__gte=timezone.now() - timedelta(days=window_days),
            reversed_at__isnull=True,
        )
        .filter(
            Q(contribution__contributor__profile__leaderboard_opt_out=False)
            | Q(contribution__contributor__profile__isnull=True)
        )
        .select_related("contribution__contributor")
    )


def _positive_int(value, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return default


def anomaly_summary() -> dict:
    """REC-006: read-only velocity and duplicate-pattern flags for Super Admin review.

    Thresholds come from the active policy's ``anomaly_review`` rules when present
    and fall back to conservative defaults. No recognition state is modified here.
    """
    policy = ScoringPolicy.objects.filter(is_active=True).first()
    rules = policy.rules if policy is not None else {}
    anomaly_rules = rules.get("anomaly_review", {}) if isinstance(rules, dict) else {}
    if not isinstance(anomaly_rules, dict):
        anomaly_rules = {}
    window_days = _positive_int(
        anomaly_rules.get("velocity_window_days"), DEFAULT_ANOMALY_WINDOW_DAYS
    )
    velocity_threshold = _positive_int(
        anomaly_rules.get("velocity_threshold"), DEFAULT_VELOCITY_THRESHOLD
    )
    duplicate_threshold = _positive_int(
        anomaly_rules.get("duplicate_threshold"), DEFAULT_DUPLICATE_THRESHOLD
    )
    start = timezone.now() - timedelta(days=window_days)
    aggregated = (
        ContributionRecord.objects.filter(
            status=VerificationStatus.ACCEPTED,
            contributor__isnull=False,
            verified_at__gte=start,
        )
        .values("contributor_id", "contributor__username")
        .annotate(accepted_count=Count("id"), distinct_titles=Count("title", distinct=True))
        .filter(
            Q(accepted_count__gte=velocity_threshold)
            | (
                Q(accepted_count__gt=F("distinct_titles"))
                & Q(accepted_count__gte=duplicate_threshold)
            )
        )
        .order_by("-accepted_count", "contributor__username")
    )
    rows = []
    for row in aggregated:
        duplicate_titles = row["accepted_count"] - row["distinct_titles"]
        rows.append(
            {
                **row,
                "duplicate_titles": duplicate_titles,
                "velocity_flag": row["accepted_count"] >= velocity_threshold,
                "duplicate_flag": duplicate_titles > 0,
            }
        )
    return {
        "rows": rows,
        "velocity_threshold": velocity_threshold,
        "duplicate_threshold": duplicate_threshold,
        "window_days": window_days,
    }
