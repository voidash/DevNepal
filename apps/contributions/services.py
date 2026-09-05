"""Contribution candidate creation, verification, and revocation services.

Implements §6.2 steps 5-7: provider events and member evidence create
CANDIDATE records (BR-006); an authorized maintainer accepts, rejects, or
requests clarification with a reason; accepted work is the only recognition
basis (REC-001), and every decision is audited and reversible (REC-005,
SEC-008).
"""

import logging
from dataclasses import dataclass

from django.db import OperationalError, ProgrammingError, transaction
from django.utils import timezone

from apps.accounts.services import require_privileged_mfa
from apps.analytics.enums import EventName
from apps.analytics.services import AnalyticsError, record_event
from apps.audit.services import record_audit
from apps.contributions.enums import ContributionSource, VerificationStatus
from apps.contributions.models import ContributionRecord
from apps.github_sync.enums import VerifiedEventKind
from apps.github_sync.webhooks import ParsedEvent
from apps.ministries.services import is_publisher_active
from apps.projects.enums import (
    ApplicationStatus,
    ContributionMode,
    ParticipationKind,
    ProjectStatus,
)
from apps.projects.models import Application, ProjectMaintainer
from apps.taxonomy.enums import TermVocabulary
from apps.taxonomy.fields import normalize_nfc
from apps.taxonomy.models import TaxonomyTerm

logger = logging.getLogger(__name__)

DECISION_STATUSES: frozenset[str] = frozenset(
    {
        VerificationStatus.ACCEPTED,
        VerificationStatus.REJECTED,
        VerificationStatus.PENDING_INFO,
    }
)
PROVIDER_REF_PREFIX = "github"
DEFAULT_GITHUB_CONTRIBUTION_SLUG = "engineering"
MAX_CONTRIBUTION_REASON_LENGTH = 2000
MAX_HOLD_RESPONSE_LENGTH = 4000


class ContributionServiceError(Exception):
    """Contribution candidate or verification flow failed."""


class UnauthorizedVerifierError(ContributionServiceError):
    """Actor is neither a maintainer of the project nor a Super Admin (BR-006)."""


class UnauthorizedRevokerError(ContributionServiceError):
    """Actor is not a Super Admin (REC-005)."""


class UnauthorizedHoldManagerError(ContributionServiceError):
    """Actor is not an OTP-verified Super Admin permitted to manage a PMO hold."""


class UnauthorizedHoldResponderError(ContributionServiceError):
    """Actor is not the affected active contributor permitted to answer a PMO hold."""


class HoldResponseAlreadyRecordedError(ContributionServiceError):
    """A bounded contributor response is already recorded for this hold."""


class InputTooLongError(ContributionServiceError):
    """A governance reason or contributor response exceeds its documented boundary."""


class SelfApprovalError(ContributionServiceError):
    """Maintainer self-credit without secondary approval or an authoritative event (BR-007, D9)."""


class InvalidSecondApproverError(ContributionServiceError):
    """Secondary approver is not another publisher of the ministry or a Super Admin (D9)."""


class InvalidDecisionError(ContributionServiceError):
    """Decision is not one of accept / reject / request clarification (§6.2 step 6)."""


class MissingReasonError(ContributionServiceError):
    """A decision or revocation was attempted without a reason (GOV-005, REC-005)."""


class InvalidStatusTransitionError(ContributionServiceError):
    """The record's current status does not permit the requested transition (REC-005)."""


class InvalidEvidenceError(ContributionServiceError):
    """Submitted evidence is not valid for an approved contribution category (BR-006, GOV-008)."""


class SubmissionNotEligibleError(ContributionServiceError):
    """The project is not open for direct member evidence submissions (DSC-005)."""


class MissingContributionTypeError(ContributionServiceError):
    """The seeded contribution-type vocabulary is unavailable for provider events."""


class RecognitionEvaluationError(ContributionServiceError):
    """Recognition scoring or badge evaluation failed after contribution acceptance."""


class ContributionAnalyticsError(ContributionServiceError):
    """A successful acceptance could not persist its required ANL-001 event."""


@dataclass(frozen=True)
class Evidence:
    """Member-submitted evidence payload; evidence, not verification (BR-006)."""

    title: str
    contribution_type: TaxonomyTerm
    description: str = ""
    evidence_url: str = ""


def record_candidate_from_github(
    parsed_event: ParsedEvent | None, project, *, contribution_type=None
) -> ContributionRecord | None:
    """§6.2 step 6 / D7 / GIT-007/GIT-008: turn a qualifying provider event into one candidate."""
    if parsed_event is None:
        return None
    if parsed_event.is_bot:
        logger.info("GIT-008 bot event %s skipped for %s", parsed_event.event_id, project)
        return None
    if parsed_event.kind not in VerifiedEventKind.values:
        return None

    ref = f"{PROVIDER_REF_PREFIX}:{parsed_event.event_id}"
    existing = ContributionRecord.objects.filter(project=project, provider_event_ref=ref).first()
    if existing is not None:
        return existing

    contributor = _resolve_github_member(parsed_event.actor_login)
    record = ContributionRecord.objects.create(
        project=project,
        contributor=contributor,
        contribution_type=contribution_type or _github_contribution_type(),
        title=_event_title(parsed_event),
        description=f"GitHub actor: {parsed_event.actor_login}",
        source=ContributionSource.PROVIDER_EVENT,
        provider_event_ref=ref,
        status=VerificationStatus.CANDIDATE,
        pending_mapping=contributor is None,
    )
    return record


def submit_evidence(member, project, evidence: Evidence) -> ContributionRecord:
    """§6.2 step 5 / BR-006: member evidence is filed as an unverified CANDIDATE record."""
    if member is None or not member.is_active:
        raise InvalidEvidenceError("evidence must be submitted by an active member")
    if not (evidence.title or "").strip():
        raise InvalidEvidenceError("evidence requires a title")
    term = evidence.contribution_type
    if term is None or term.vocabulary != TermVocabulary.CONTRIBUTION_TYPE or not term.is_active:
        raise InvalidEvidenceError("evidence requires an approved contribution type (GOV-008)")
    if not can_submit_evidence(member, project):
        raise SubmissionNotEligibleError(
            "evidence submissions require an open project with either a direct contribution route "
            "or an accepted application (DSC-005)"
        )

    return ContributionRecord.objects.create(
        project=project,
        contributor=member,
        contribution_type=term,
        title=evidence.title.strip(),
        description=evidence.description,
        evidence_url=evidence.evidence_url,
        source=ContributionSource.MEMBER_SUBMISSION,
        status=VerificationStatus.CANDIDATE,
    )


def can_submit_evidence(member, project) -> bool:
    """DSC-005: direct work is eligible while application work requires an accepted application."""
    if member is None or not member.is_active:
        return False
    if project.status != ProjectStatus.OPEN_FOR_CONTRIBUTION:
        return False
    if project.contribution_mode in {ContributionMode.OPEN_DIRECT, ContributionMode.HYBRID}:
        return True
    return Application.objects.filter(
        project=project,
        applicant=member,
        kind=ParticipationKind.APPLICATION,
        status=ApplicationStatus.ACCEPTED,
    ).exists()


def verify(
    verifier,
    record: ContributionRecord,
    decision,
    reason: str,
    *,
    second_approval_by=None,
) -> ContributionRecord:
    """§6.2 step 6 / BR-006 / BR-007 / D9: accept, reject, or request clarification."""
    reason = _require_reason(reason)
    if decision not in DECISION_STATUSES:
        raise InvalidDecisionError("decision must be accepted, rejected, or pending_info")
    if not _is_authorized_verifier(verifier, record):
        _audit_decision(verifier, record, "contribution.verify.denied", {}, {"decision": decision})
        raise UnauthorizedVerifierError(
            "verification requires a maintainer of this project or a Super Admin (BR-006)"
        )
    if record.status == VerificationStatus.REVOKED:
        raise InvalidStatusTransitionError("revoked records cannot be re-verified (REC-005)")
    if record.hold_active:
        raise InvalidStatusTransitionError(
            "PMO-held records must be released before a verification decision can be recorded "
            "(D4.1)"
        )

    before = {"status": record.status}
    if record.status == VerificationStatus.ACCEPTED:
        _audit_decision(
            verifier, record, "contribution.verify.denied", before, {"decision": decision}
        )
        raise InvalidStatusTransitionError(
            "accepted records can only be reversed through Super Admin revocation (REC-005)"
        )
    if record.contributor_id is not None and record.contributor_id == verifier.pk:
        if record.source != ContributionSource.PROVIDER_EVENT:
            if second_approval_by is None:
                _audit_decision(
                    verifier, record, "contribution.verify.denied", before, {"decision": decision}
                )
                raise SelfApprovalError(
                    "self-verification requires secondary approval or an authoritative "
                    "provider event (BR-007, D9)"
                )
            if not _is_valid_second_approver(second_approval_by, verifier, record):
                _audit_decision(
                    verifier, record, "contribution.verify.denied", before, {"decision": decision}
                )
                raise InvalidSecondApproverError(
                    "secondary approval requires another publisher of the ministry "
                    "or a Super Admin (D9)"
                )
            record.secondary_approval_by = second_approval_by

    with transaction.atomic():
        record.status = decision
        record.verified_by = verifier
        record.verified_at = timezone.now()
        record.verification_note = reason
        record.save()

        after = {"status": record.status, "reason": reason}
        if record.secondary_approval_by_id is not None:
            after["secondary_approval_by"] = record.secondary_approval_by.username
        _audit_decision(verifier, record, f"contribution.{decision}", before, after)

        if decision == VerificationStatus.ACCEPTED:
            link_profile_credit(record)
            if record.project.ministry_id is not None:
                try:
                    record_event(
                        EventName.CONTRIBUTION_ACCEPTED,
                        project=record.project,
                        source_ref=f"contribution:{record.pk}",
                    )
                except AnalyticsError as error:
                    logger.exception(
                        "Contribution analytics recording failed; contribution_id=%s", record.pk
                    )
                    raise ContributionAnalyticsError(
                        "contribution analytics event could not be recorded"
                    ) from error
    return record


def revoke(super_admin, record: ContributionRecord, reason: str) -> ContributionRecord:
    """REC-005 / A5: reverse recognition with a reason and an audit record."""
    reason = _require_reason(reason)
    if not (super_admin is not None and super_admin.is_active and super_admin.is_superuser):
        _audit_decision(
            super_admin, record, "contribution.revoke.denied", {"status": record.status}, {}
        )
        raise UnauthorizedRevokerError("revocation requires a Super Admin (REC-005)")
    require_privileged_mfa(
        super_admin,
        action="contribution.revoke",
        obj=record,
        error_type=UnauthorizedRevokerError,
    )
    if record.status != VerificationStatus.ACCEPTED:
        raise InvalidStatusTransitionError("only accepted contributions can be reversed (REC-005)")

    with transaction.atomic():
        before = {"status": record.status}
        record.status = VerificationStatus.REVOKED
        record.revoked_by = super_admin
        record.revoked_at = timezone.now()
        record.revocation_reason = reason
        record.save()
        try:
            from apps.recognition.services import RecognitionError, reverse_accepted_contribution

            reverse_accepted_contribution(super_admin, record, reason)
        except RecognitionError as error:
            logger.exception("Recognition reversal failed for contribution %s", record.pk)
            raise RecognitionEvaluationError(
                f"recognition reversal failed for contribution {record.pk}"
            ) from error
        _audit_decision(
            super_admin,
            record,
            "contribution.revoked",
            before,
            {"status": record.status, "reason": reason},
        )
    return record


def place_on_hold(pmo, record: ContributionRecord, reason: str) -> ContributionRecord:
    """D4.1/REC-006: PMO temporarily holds an unscored outcome for anomaly review.

    This transition deliberately applies only before acceptance.  Accepted work has
    score and badge side effects and must use the REC-005 revocation flow until a
    separately designed restoration workflow exists.
    """
    reason = _require_reason(reason)
    _require_hold_manager(pmo, record, action="contribution.hold")
    with transaction.atomic():
        locked = ContributionRecord.objects.select_for_update().get(pk=record.pk)
        if locked.hold_active or locked.status not in {
            VerificationStatus.CANDIDATE,
            VerificationStatus.PENDING_INFO,
        }:
            _audit_decision(
                pmo,
                locked,
                "contribution.hold.denied",
                {"status": locked.status},
                {},
            )
            raise InvalidStatusTransitionError(
                "only unscored candidate or clarification outcomes can be placed on hold (D4.1)"
            )
        before = {"status": locked.status, "hold_active": False}
        locked.held_from_status = locked.status
        locked.hold_active = True
        locked.hold_reason = reason
        locked.held_by = pmo
        locked.held_at = timezone.now()
        locked.hold_released_by = None
        locked.hold_released_at = None
        locked.hold_release_reason = ""
        locked.hold_response = ""
        locked.hold_responded_at = None
        locked.save(
            update_fields=[
                "held_from_status",
                "hold_active",
                "hold_reason",
                "held_by",
                "held_at",
                "hold_released_by",
                "hold_released_at",
                "hold_release_reason",
                "hold_response",
                "hold_responded_at",
                "updated_at",
            ]
        )
        _audit_decision(
            pmo,
            locked,
            "contribution.held",
            before,
            {
                "status": locked.status,
                "hold_active": True,
                "held_from_status": locked.held_from_status,
                "reason": reason,
            },
        )
    return locked


def release_hold(pmo, record: ContributionRecord, reason: str) -> ContributionRecord:
    """D4.3/REC-006: restore the exact pre-hold unscored outcome with an audit reason."""
    reason = _require_reason(reason)
    _require_hold_manager(pmo, record, action="contribution.release_hold")
    with transaction.atomic():
        locked = ContributionRecord.objects.select_for_update().get(pk=record.pk)
        if not locked.hold_active or locked.held_from_status not in {
            VerificationStatus.CANDIDATE,
            VerificationStatus.PENDING_INFO,
        }:
            _audit_decision(
                pmo,
                locked,
                "contribution.release_hold.denied",
                {"status": locked.status},
                {},
            )
            raise InvalidStatusTransitionError("only an active PMO hold can be released (D4.3)")
        before = {"status": locked.status, "hold_active": True}
        locked.hold_active = False
        locked.hold_released_by = pmo
        locked.hold_released_at = timezone.now()
        locked.hold_release_reason = reason
        locked.save(
            update_fields=[
                "hold_active",
                "hold_released_by",
                "hold_released_at",
                "hold_release_reason",
                "updated_at",
            ]
        )
        _audit_decision(
            pmo,
            locked,
            "contribution.hold_released",
            before,
            {"status": locked.status, "hold_active": False, "reason": reason},
        )
    return locked


def respond_to_hold(contributor, record: ContributionRecord, response: str) -> ContributionRecord:
    """D4.2/REC-006: the affected contributor gives one reasoned response while held.

    The response is intentionally bounded to one immutable-in-practice record.  A
    correction or consolidation decision belongs to the later D4.3 workflow, not
    to a contributor-controlled edit path.
    """
    response = _require_hold_response(response)
    if (
        contributor is None
        or not contributor.is_active
        or record.contributor_id is None
        or record.contributor_id != contributor.pk
    ):
        _audit_decision(
            contributor,
            record,
            "contribution.hold_response.denied",
            {"status": record.status},
            {},
        )
        raise UnauthorizedHoldResponderError(
            "only the affected active contributor can respond to a PMO hold (D4.2)"
        )
    with transaction.atomic():
        locked = ContributionRecord.objects.select_for_update().get(pk=record.pk)
        if not locked.hold_active:
            _audit_decision(
                contributor,
                locked,
                "contribution.hold_response.denied",
                {"status": locked.status},
                {},
            )
            raise InvalidStatusTransitionError("a response can be recorded only while held (D4.2)")
        if locked.hold_responded_at is not None or locked.hold_response:
            _audit_decision(
                contributor,
                locked,
                "contribution.hold_response.denied",
                {"status": locked.status},
                {},
            )
            raise HoldResponseAlreadyRecordedError(
                "a contributor response is already recorded for this PMO hold (D4.2)"
            )
        locked.hold_response = response
        locked.hold_responded_at = timezone.now()
        locked.save(update_fields=["hold_response", "hold_responded_at", "updated_at"])
        _audit_decision(
            contributor,
            locked,
            "contribution.hold_responded",
            {"status": locked.status},
            {"status": locked.status, "response": response},
        )
    return locked


def accepted_contributions(member):
    """REC-001: the recognition and verified-portfolio basis is ACCEPTED records only."""
    return member.contributions.filter(status=VerificationStatus.ACCEPTED).select_related(
        "contribution_type", "project"
    )


def link_profile_credit(record: ContributionRecord) -> ContributionRecord:
    """REC-001/REC-002: evaluate accepted work against the active recognition policy."""
    try:
        from apps.recognition.services import RecognitionError, evaluate_accepted_contribution

        evaluate_accepted_contribution(record)
    except RecognitionError as error:
        logger.exception("Recognition evaluation failed for accepted contribution %s", record.pk)
        raise RecognitionEvaluationError(
            f"recognition evaluation failed for contribution {record.pk}"
        ) from error
    return record


def _require_reason(reason: str) -> str:
    stripped = normalize_nfc(reason or "")
    if not stripped:
        raise MissingReasonError("a reason is required for every contribution decision (GOV-005)")
    if len(stripped) > MAX_CONTRIBUTION_REASON_LENGTH:
        raise InputTooLongError(
            "a contribution decision reason cannot exceed "
            f"{MAX_CONTRIBUTION_REASON_LENGTH} characters"
        )
    return stripped


def _require_hold_response(response: str) -> str:
    stripped = normalize_nfc(response or "")
    if not stripped:
        raise MissingReasonError("a contributor response is required for a PMO hold (D4.2)")
    if len(stripped) > MAX_HOLD_RESPONSE_LENGTH:
        raise InputTooLongError(
            f"a PMO hold response cannot exceed {MAX_HOLD_RESPONSE_LENGTH} characters"
        )
    return stripped


def _is_authorized_verifier(verifier, record: ContributionRecord) -> bool:
    if verifier is None or not verifier.is_active:
        return False
    if verifier.is_superuser:
        require_privileged_mfa(
            verifier,
            action="contribution.verify",
            obj=record,
            error_type=UnauthorizedVerifierError,
        )
        return True
    return ProjectMaintainer.objects.filter(
        project_id=record.project_id, user_id=verifier.pk
    ).exists()


def _require_hold_manager(actor, record: ContributionRecord, *, action: str) -> None:
    if actor is None or not actor.is_active or not actor.is_superuser:
        _audit_decision(actor, record, f"{action}.denied", {"status": record.status}, {})
        raise UnauthorizedHoldManagerError("PMO outcome holds require a Super Admin (D4.1)")
    require_privileged_mfa(
        actor,
        action=action,
        obj=record,
        error_type=UnauthorizedHoldManagerError,
    )


def _is_valid_second_approver(approver, verifier, record: ContributionRecord) -> bool:
    if approver is None or not approver.is_active or approver.pk == verifier.pk:
        return False
    if approver.is_superuser:
        require_privileged_mfa(
            approver,
            action="contribution.verify",
            obj=record,
            error_type=InvalidSecondApproverError,
        )
        return True
    if not is_publisher_active(approver, record.project.ministry):
        return False
    require_privileged_mfa(
        approver,
        action="contribution.verify",
        obj=record,
        error_type=InvalidSecondApproverError,
    )
    return True


def _resolve_github_member(actor_login: str):
    """GIT-012 actor mapping via GithubConnection.login; None while that model is pending."""
    if not actor_login:
        return None
    try:
        from apps.github_sync.models import GithubConnection
    except ImportError:
        return None
    try:
        connection = (
            GithubConnection.objects.filter(login=actor_login, revoked_at__isnull=True)
            .select_related("user")
            .first()
        )
    except (OperationalError, ProgrammingError):
        logger.warning("GIT-012 actor mapping skipped: github_sync migrations are not applied yet")
        return None
    return connection.user if connection else None


def _github_contribution_type() -> TaxonomyTerm:
    term = TaxonomyTerm.objects.filter(
        vocabulary=TermVocabulary.CONTRIBUTION_TYPE,
        slug=DEFAULT_GITHUB_CONTRIBUTION_SLUG,
        is_active=True,
    ).first()
    if term is None:
        raise MissingContributionTypeError(
            "provider-event candidates require the seeded engineering contribution type"
        )
    return term


def _event_title(parsed_event: ParsedEvent) -> str:
    number = parsed_event.number
    number_part = f"#{number} " if number is not None else ""
    repository = parsed_event.repository_name
    titles = {
        VerifiedEventKind.PR_MERGED: f"Merged pull request {number_part}in {repository}",
        VerifiedEventKind.ISSUE_COMPLETED: f"Completed issue {number_part}in {repository}",
        VerifiedEventKind.REVIEW_APPROVED: (
            f"Approved review on pull request {number_part}in {repository}"
        ),
        VerifiedEventKind.RELEASE_PUBLISHED: f"Published release in {repository}",
    }
    return titles[parsed_event.kind]


def _audit_decision(actor, record: ContributionRecord, action: str, before: dict, after: dict):
    record_audit(
        actor=actor,
        action=action,
        obj=record,
        before=before,
        after=after,
        result="failure" if action.endswith(".denied") else "success",
    )
