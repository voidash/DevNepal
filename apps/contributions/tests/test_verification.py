import pytest
from django.db import IntegrityError, transaction
from django.test import override_settings

from apps.audit.models import AuditEvent
from apps.contributions.enums import ContributionSource, VerificationStatus
from apps.contributions.services import (
    Evidence,
    HoldResponseAlreadyRecordedError,
    InputTooLongError,
    InvalidDecisionError,
    InvalidSecondApproverError,
    InvalidStatusTransitionError,
    MissingReasonError,
    SelfApprovalError,
    UnauthorizedHoldManagerError,
    UnauthorizedHoldResponderError,
    UnauthorizedRevokerError,
    UnauthorizedVerifierError,
    accepted_contributions,
    link_profile_credit,
    place_on_hold,
    release_hold,
    respond_to_hold,
    revoke,
    submit_evidence,
    verify,
)
from apps.contributions.tests.factories import ContributionRecordFactory, contribution_type
from apps.ministries.enums import PublisherStatus
from apps.ministries.tests.factories import (
    MinistryOrganizationFactory,
    MinistryPublisherFactory,
    SuperAdminFactory,
    UserFactory,
)
from apps.projects.enums import ContributionMode, ProjectStatus
from apps.projects.tests.factories import ProjectFactory, ProjectMaintainerFactory
from apps.recognition.enums import AwardStatus
from apps.recognition.models import BadgeAward, ContributionScore
from apps.recognition.services import activate_policy
from apps.recognition.tests.factories import BadgeFactory

pytestmark = [pytest.mark.django_db]


@pytest.fixture
def maintained_project():
    return ProjectFactory(
        status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
        contribution_mode=ContributionMode.OPEN_DIRECT,
    )


@pytest.fixture
def maintainer(maintained_project):
    return ProjectMaintainerFactory(project=maintained_project).user


@pytest.fixture
def candidate(maintained_project):
    return ContributionRecordFactory(project=maintained_project)


def audits_for(record):
    return AuditEvent.objects.filter(
        content_type__app_label="contributions",
        content_type__model="contributionrecord",
        object_id=str(record.pk),
    )


@pytest.mark.unit
def test_non_maintainer_cannot_verify_and_denial_is_audited(maintained_project, candidate):
    """BR-006/AUTH-006/SEC-008: only a project maintainer or Super Admin may verify."""
    outsider = UserFactory()

    with pytest.raises(UnauthorizedVerifierError):
        verify(outsider, candidate, VerificationStatus.ACCEPTED, "looks fine")

    candidate.refresh_from_db()
    assert candidate.status == VerificationStatus.CANDIDATE
    denial = audits_for(candidate).filter(action="contribution.verify.denied", result="failure")
    assert denial.count() == 1
    assert denial.get().actor == outsider


@pytest.mark.unit
def test_maintainer_of_another_project_cannot_verify(candidate, maintained_project):
    """BR-006/AUTH-006: verification authority is scoped to THAT project's maintainers."""
    other_maintainer = ProjectMaintainerFactory().user

    with pytest.raises(UnauthorizedVerifierError):
        verify(other_maintainer, candidate, VerificationStatus.ACCEPTED, "not my project")

    candidate.refresh_from_db()
    assert candidate.status == VerificationStatus.CANDIDATE


@pytest.mark.unit
def test_maintainer_acceptance_makes_the_contribution_official(maintainer, candidate):
    """BR-006/§6.2 step 6: authorized maintainer acceptance verifies the record, with reason."""
    verified = verify(maintainer, candidate, VerificationStatus.ACCEPTED, "Merged after review")

    assert verified.status == VerificationStatus.ACCEPTED
    assert verified.verified_by == maintainer
    assert verified.verified_at is not None
    assert verified.verification_note == "Merged after review"
    entry = audits_for(candidate).get(action="contribution.accepted")
    assert entry.actor == maintainer
    assert entry.before == {"status": VerificationStatus.CANDIDATE}
    assert entry.after["reason"] == "Merged after review"


@pytest.mark.unit
@override_settings(RECOGNITION_ENABLED=True)
def test_acceptance_scores_and_evaluates_badges_under_the_active_policy(maintainer, candidate):
    """REC-001/REC-002: accepted work is scored and evaluated against the active policy."""
    admin = SuperAdminFactory()
    badge = BadgeFactory(slug="verified-contributor")
    policy = activate_policy(
        admin,
        {"standard": 3, "badges": {badge.slug: {"minimum_points": 3}}},
    )

    verify(maintainer, candidate, VerificationStatus.ACCEPTED, "Merged after review")

    score = ContributionScore.objects.get(contribution=candidate)
    award = BadgeAward.objects.get(recipient=candidate.contributor, badge=badge)
    assert score.policy == policy
    assert score.points == 3
    assert award.contribution == candidate
    assert AuditEvent.objects.filter(
        action="recognition.contribution_scored", object_id=str(score.pk)
    ).exists()
    assert AuditEvent.objects.filter(
        action="recognition.badge_awarded", object_id=str(award.pk)
    ).exists()


@pytest.mark.unit
def test_acceptance_does_not_publish_recognition_while_the_gate_is_disabled(maintainer, candidate):
    """REC-001/D12: the disabled public-recognition gate prevents scoring and badge awards."""
    admin = SuperAdminFactory()
    badge = BadgeFactory(slug="verified-contributor")
    activate_policy(admin, {"standard": 3, "badges": {badge.slug: {"minimum_points": 3}}})

    verify(maintainer, candidate, VerificationStatus.ACCEPTED, "Merged after review")

    assert not ContributionScore.objects.filter(contribution=candidate).exists()
    assert not BadgeAward.objects.filter(recipient=candidate.contributor, badge=badge).exists()


@pytest.mark.unit
def test_maintainer_rejects_with_reason(maintainer, candidate):
    """BR-006: a rejection records the decision and its reason."""
    verified = verify(maintainer, candidate, VerificationStatus.REJECTED, "Duplicate of #4")

    assert verified.status == VerificationStatus.REJECTED
    assert verified.verification_note == "Duplicate of #4"
    assert audits_for(candidate).filter(action="contribution.rejected").exists()


@pytest.mark.unit
def test_maintainer_requests_clarification_then_accepts(maintainer, candidate):
    """BR-006: clarification can be requested with a reason and later resolved."""
    verify(maintainer, candidate, VerificationStatus.PENDING_INFO, "Which issue does this close?")
    candidate.refresh_from_db()
    assert candidate.status == VerificationStatus.PENDING_INFO

    verify(maintainer, candidate, VerificationStatus.ACCEPTED, "Evidence links the issue")
    candidate.refresh_from_db()
    assert candidate.status == VerificationStatus.ACCEPTED
    assert audits_for(candidate).count() == 2


@pytest.mark.unit
@pytest.mark.parametrize(
    "decision",
    [
        VerificationStatus.ACCEPTED,
        VerificationStatus.REJECTED,
        VerificationStatus.PENDING_INFO,
    ],
)
def test_maintainer_cannot_transition_an_accepted_contribution(maintainer, candidate, decision):
    """REC-005/SEC-008: accepted work is immutable outside the Super Admin revocation path."""
    verify(maintainer, candidate, VerificationStatus.ACCEPTED, "Accepted")

    with pytest.raises(InvalidStatusTransitionError):
        verify(maintainer, candidate, decision, "Attempted rewrite")

    candidate.refresh_from_db()
    assert candidate.status == VerificationStatus.ACCEPTED
    assert (
        audits_for(candidate).filter(action="contribution.verify.denied", result="failure").exists()
    )


@pytest.mark.unit
def test_decision_requires_a_reason(maintainer, candidate):
    """GOV-005/§6.2: every decision carries a recorded reason."""
    with pytest.raises(MissingReasonError):
        verify(maintainer, candidate, VerificationStatus.ACCEPTED, "  ")


@pytest.mark.unit
def test_non_decision_statuses_are_refused(maintainer, candidate):
    """BR-006: only accept, reject, and request-clarification are decisions."""
    with pytest.raises(InvalidDecisionError):
        verify(maintainer, candidate, VerificationStatus.CANDIDATE, "not a decision")
    with pytest.raises(InvalidDecisionError):
        verify(maintainer, candidate, VerificationStatus.REVOKED, "not a decision")


@pytest.mark.unit
def test_pmo_can_hold_and_release_unscored_evidence_with_auditable_reasons(candidate):
    """D4.1/D4.3/REC-006: PMO holds and releases a candidate without deleting it."""
    pmo = SuperAdminFactory()

    held = place_on_hold(pmo, candidate, "Burst activity needs an anomaly review.")

    assert held.status == VerificationStatus.CANDIDATE
    assert held.hold_active is True
    assert held.held_from_status == VerificationStatus.CANDIDATE
    assert held.held_by == pmo
    assert held.hold_reason == "Burst activity needs an anomaly review."
    hold_audit = audits_for(candidate).get(action="contribution.held")
    assert hold_audit.before == {"status": VerificationStatus.CANDIDATE, "hold_active": False}
    assert hold_audit.after["reason"] == "Burst activity needs an anomaly review."

    released = release_hold(pmo, candidate, "Maintainer confirmed the records are distinct.")

    assert released.status == VerificationStatus.CANDIDATE
    assert released.hold_released_by == pmo
    assert released.hold_released_at is not None
    assert released.hold_release_reason == "Maintainer confirmed the records are distinct."
    release_audit = audits_for(candidate).get(action="contribution.hold_released")
    assert release_audit.before == {"status": VerificationStatus.CANDIDATE, "hold_active": True}
    assert release_audit.after["status"] == VerificationStatus.CANDIDATE
    assert release_audit.after["hold_active"] is False


@pytest.mark.unit
def test_hold_requires_pmo_authority_mfa_and_a_reason(candidate, maintainer):
    """D4.1/AUTH-005/REC-006: a publisher cannot silently suppress a contribution outcome."""
    with pytest.raises(UnauthorizedHoldManagerError):
        place_on_hold(maintainer, candidate, "Not authorized")
    with pytest.raises(MissingReasonError):
        place_on_hold(SuperAdminFactory(), candidate, " ")

    candidate.refresh_from_db()
    assert candidate.status == VerificationStatus.CANDIDATE
    assert (
        audits_for(candidate).filter(action="contribution.hold.denied", result="failure").exists()
    )


@pytest.mark.unit
def test_accepted_contribution_uses_rec005_revocation_not_reversible_hold(candidate, maintainer):
    """D4.3/REC-005: credited work cannot enter a hold without score-restoration semantics."""
    verify(maintainer, candidate, VerificationStatus.ACCEPTED, "Accepted before review")

    with pytest.raises(InvalidStatusTransitionError):
        place_on_hold(SuperAdminFactory(), candidate, "Investigating credited work")

    candidate.refresh_from_db()
    assert candidate.status == VerificationStatus.ACCEPTED


@pytest.mark.unit
def test_on_hold_rows_require_durable_governance_metadata_at_the_database_boundary(candidate):
    """D4.1/REC-006: direct writes cannot create an unauditable hold state."""
    candidate.hold_active = True

    with pytest.raises(IntegrityError), transaction.atomic():
        candidate.save(update_fields=["hold_active", "updated_at"])

    candidate.refresh_from_db()
    assert candidate.status == VerificationStatus.CANDIDATE
    assert candidate.hold_active is False


@pytest.mark.unit
def test_repeated_hold_release_cycles_keep_every_reason_in_the_audit_history(candidate):
    """D4.1/D4.3/REC-006: latest columns may change, but audit evidence is append-only."""
    pmo = SuperAdminFactory()
    place_on_hold(pmo, candidate, "First anomaly review")
    release_hold(pmo, candidate, "First review cleared")
    place_on_hold(pmo, candidate, "Second anomaly review")
    release_hold(pmo, candidate, "Second review cleared")

    history = list(
        audits_for(candidate)
        .filter(action__in=("contribution.held", "contribution.hold_released"))
        .order_by("created_at", "pk")
    )
    assert [event.action for event in history] == [
        "contribution.held",
        "contribution.hold_released",
        "contribution.held",
        "contribution.hold_released",
    ]
    assert [event.after["reason"] for event in history] == [
        "First anomaly review",
        "First review cleared",
        "Second anomaly review",
        "Second review cleared",
    ]


@pytest.mark.unit
def test_new_hold_cycle_clears_the_previous_response_without_erasing_its_audit_event(candidate):
    """D4.2/D4.3: a new hold gets a fresh response while the prior response remains audited."""
    pmo = SuperAdminFactory()
    place_on_hold(pmo, candidate, "First review")
    respond_to_hold(candidate.contributor, candidate, "First contributor response")
    release_hold(pmo, candidate, "First review cleared")

    place_on_hold(pmo, candidate, "Second review")
    candidate.refresh_from_db()
    assert candidate.hold_response == ""
    assert candidate.hold_responded_at is None

    respond_to_hold(candidate.contributor, candidate, "Second contributor response")
    responses = list(
        audits_for(candidate)
        .filter(action="contribution.hold_responded")
        .order_by("created_at", "pk")
    )
    assert [event.after["response"] for event in responses] == [
        "First contributor response",
        "Second contributor response",
    ]


@pytest.mark.unit
def test_affected_contributor_can_answer_one_active_hold_and_pmo_audit_keeps_it(candidate):
    """D4.2/REC-006: the member, not a maintainer, provides one retained hold response."""
    pmo = SuperAdminFactory()
    place_on_hold(pmo, candidate, "Please explain this rapid batch.")

    responded = respond_to_hold(
        candidate.contributor,
        candidate,
        "The tasks were pre-agreed accessibility fixes with separate test evidence.",
    )

    assert responded.hold_response.startswith("The tasks were pre-agreed")
    assert responded.hold_responded_at is not None
    audit = audits_for(candidate).get(action="contribution.hold_responded")
    assert audit.actor == candidate.contributor
    assert audit.after["response"] == responded.hold_response
    with pytest.raises(HoldResponseAlreadyRecordedError):
        respond_to_hold(
            candidate.contributor, candidate, "A second response must not overwrite the first."
        )


@pytest.mark.unit
def test_other_members_cannot_answer_a_hold(candidate):
    """D4.2/AUTH-006: PMO receives a response only from the affected contributor."""
    place_on_hold(SuperAdminFactory(), candidate, "Please explain this activity.")

    with pytest.raises(UnauthorizedHoldResponderError):
        respond_to_hold(UserFactory(), candidate, "Forged response")

    candidate.refresh_from_db()
    assert candidate.hold_response == ""
    assert (
        audits_for(candidate)
        .filter(action="contribution.hold_response.denied", result="failure")
        .exists()
    )


@pytest.mark.unit
def test_hold_response_timestamp_cannot_be_persisted_without_text(candidate):
    """D4.2: the database prevents a false indication that the contributor responded."""
    from django.utils import timezone

    candidate.hold_responded_at = timezone.now()
    with pytest.raises(IntegrityError), transaction.atomic():
        candidate.save(update_fields=["hold_responded_at", "updated_at"])


@pytest.mark.unit
def test_hold_response_is_nfc_normalized_and_bounded(candidate):
    """D4.2/DSC-003: PMO receives one normalized response within the documented limit."""
    place_on_hold(SuperAdminFactory(), candidate, "Please explain this activity.")

    recorded = respond_to_hold(candidate.contributor, candidate, "  Re\u0301ponse  ")
    assert recorded.hold_response == "Réponse"

    second = ContributionRecordFactory()
    place_on_hold(SuperAdminFactory(), second, "Please explain this activity.")
    with pytest.raises(InputTooLongError):
        respond_to_hold(second.contributor, second, "x" * 4001)


@pytest.mark.unit
def test_self_verification_is_blocked_without_secondary_approval(maintainer, maintained_project):
    """BR-007/D9: a maintainer awarding credit to themselves needs secondary approval."""
    own_record = ContributionRecordFactory(project=maintained_project, contributor=maintainer)

    with pytest.raises(SelfApprovalError):
        verify(maintainer, own_record, VerificationStatus.ACCEPTED, "trust me")

    own_record.refresh_from_db()
    assert own_record.status == VerificationStatus.CANDIDATE
    assert (
        audits_for(own_record)
        .filter(action="contribution.verify.denied", result="failure")
        .exists()
    )


@pytest.mark.unit
def test_self_verification_succeeds_with_second_approver_publisher(maintainer, maintained_project):
    """BR-007/D9: another ACTIVE publisher of the same ministry may second self-credit."""
    own_record = ContributionRecordFactory(project=maintained_project, contributor=maintainer)
    second = MinistryPublisherFactory(ministry=maintained_project.ministry).user

    verified = verify(
        maintainer,
        own_record,
        VerificationStatus.ACCEPTED,
        "Publisher reviewed the evidence",
        second_approval_by=second,
    )

    assert verified.status == VerificationStatus.ACCEPTED
    assert verified.secondary_approval_by == second


@pytest.mark.unit
def test_self_verification_succeeds_with_super_admin_second_approver(maintained_project):
    """BR-007/D9: a Super Admin is always a valid secondary approver."""
    maintainer = ProjectMaintainerFactory(project=maintained_project).user
    own_record = ContributionRecordFactory(project=maintained_project, contributor=maintainer)

    verified = verify(
        maintainer,
        own_record,
        VerificationStatus.ACCEPTED,
        "Escalated for review",
        second_approval_by=SuperAdminFactory(),
    )

    assert verified.status == VerificationStatus.ACCEPTED


@pytest.mark.unit
@pytest.mark.parametrize(
    "second_factory",
    ["other_ministry", "revoked_publisher", "self"],
)
def test_invalid_second_approvers_are_refused(maintained_project, second_factory):
    """BR-007/D9: secondary approval must be another publisher of THIS ministry or a Super Admin."""
    maintainer = ProjectMaintainerFactory(project=maintained_project).user
    own_record = ContributionRecordFactory(project=maintained_project, contributor=maintainer)

    if second_factory == "other_ministry":
        second = MinistryPublisherFactory(ministry=MinistryOrganizationFactory()).user
    elif second_factory == "revoked_publisher":
        second = MinistryPublisherFactory(
            ministry=maintained_project.ministry, status=PublisherStatus.REVOKED
        ).user
    else:
        second = maintainer

    with pytest.raises(InvalidSecondApproverError):
        verify(
            maintainer,
            own_record,
            VerificationStatus.ACCEPTED,
            "attempted self-second",
            second_approval_by=second,
        )
    own_record.refresh_from_db()
    assert own_record.status == VerificationStatus.CANDIDATE


@pytest.mark.unit
def test_authoritative_provider_event_exempts_self_approval(maintained_project):
    """BR-007/D9: an automated authoritative event satisfies secondary approval by itself."""
    maintainer = ProjectMaintainerFactory(project=maintained_project).user
    event_record = ContributionRecordFactory(
        project=maintained_project,
        contributor=maintainer,
        provider_event=True,
        provider_event_ref="github:31337",
    )

    verified = verify(maintainer, event_record, VerificationStatus.ACCEPTED, "Authoritative merge")

    assert verified.status == VerificationStatus.ACCEPTED
    assert verified.secondary_approval_by is None


@pytest.mark.unit
def test_revoked_records_cannot_be_reverified(maintainer, maintained_project, candidate):
    """REC-005: a reversed recognition is terminal for verification."""
    verify(maintainer, candidate, VerificationStatus.ACCEPTED, "Accepted")
    revoke(SuperAdminFactory(), candidate, "Gaming detected")

    with pytest.raises(InvalidStatusTransitionError):
        verify(maintainer, candidate, VerificationStatus.ACCEPTED, "try again")


@pytest.mark.unit
def test_revocation_requires_super_admin(candidate, maintainer):
    """REC-005/SEC-008: a plain maintainer cannot reverse recognition."""
    verify(maintainer, candidate, VerificationStatus.ACCEPTED, "Accepted")

    with pytest.raises(UnauthorizedRevokerError):
        revoke(maintainer, candidate, "should fail")

    candidate.refresh_from_db()
    assert candidate.status == VerificationStatus.ACCEPTED
    assert (
        audits_for(candidate).filter(action="contribution.revoke.denied", result="failure").exists()
    )


@pytest.mark.unit
@override_settings(RECOGNITION_ENABLED=True)
def test_super_admin_revocation_reverses_recognition_with_audit(candidate, maintainer):
    """REC-005/A5: revocation records who, when, why, and lands in the audit trail."""
    policy_admin = SuperAdminFactory()
    badge = BadgeFactory(slug="revocable-verified-contributor")
    activate_policy(
        policy_admin,
        {"standard": 3, "badges": {badge.slug: {"minimum_points": 3}}},
    )
    verify(maintainer, candidate, VerificationStatus.ACCEPTED, "Accepted")
    super_admin = SuperAdminFactory()

    revoked = revoke(super_admin, candidate, "Plagiarized work")

    assert revoked.status == VerificationStatus.REVOKED
    assert revoked.revoked_by == super_admin
    assert revoked.revoked_at is not None
    assert revoked.revocation_reason == "Plagiarized work"
    entry = audits_for(candidate).get(action="contribution.revoked")
    assert entry.actor == super_admin
    assert entry.before == {"status": VerificationStatus.ACCEPTED}
    assert entry.after["reason"] == "Plagiarized work"
    score = ContributionScore.objects.get(contribution=candidate)
    assert score.reversed_at is not None
    assert score.reversal_reason == "Plagiarized work"
    award = BadgeAward.objects.get(contribution=candidate, badge=badge)
    assert award.status == AwardStatus.REVOKED
    assert award.revocation_reason == "Plagiarized work"
    assert AuditEvent.objects.filter(
        action="recognition.contribution_score_reversed", object_id=str(score.pk)
    ).exists()
    assert AuditEvent.objects.filter(
        action="recognition.badge_revoked", object_id=str(award.pk)
    ).exists()


@pytest.mark.unit
def test_unverified_super_admin_cannot_verify_and_denial_leaves_record_unchanged(candidate):
    """AUTH-005/AUTH-007/BR-006/SEC-008: superadmin verification requires the verified session."""
    super_admin = UserFactory(is_superuser=True, is_staff=True)

    with pytest.raises(UnauthorizedVerifierError):
        verify(super_admin, candidate, VerificationStatus.ACCEPTED, "Attempted override")

    candidate.refresh_from_db()
    assert candidate.status == VerificationStatus.CANDIDATE
    assert (
        audits_for(candidate)
        .filter(actor=super_admin, action="contribution.verify.denied", result="failure")
        .exists()
    )


@pytest.mark.unit
def test_unverified_super_admin_cannot_revoke_and_denial_leaves_record_unchanged(
    candidate, maintainer
):
    """AUTH-005/AUTH-007/REC-005/SEC-008: superadmin revocation requires the verified session."""
    verify(maintainer, candidate, VerificationStatus.ACCEPTED, "Accepted")
    super_admin = UserFactory(is_superuser=True, is_staff=True)

    with pytest.raises(UnauthorizedRevokerError):
        revoke(super_admin, candidate, "Attempted override")

    candidate.refresh_from_db()
    assert candidate.status == VerificationStatus.ACCEPTED
    assert (
        audits_for(candidate)
        .filter(actor=super_admin, action="contribution.revoke.denied", result="failure")
        .exists()
    )


@pytest.mark.unit
def test_unverified_publisher_cannot_second_self_approval_and_denial_leaves_record_unchanged(
    maintained_project,
):
    """AUTH-005/AUTH-007/BR-007/SEC-008: publisher second approval requires the verified session."""
    maintainer = ProjectMaintainerFactory(project=maintained_project).user
    record = ContributionRecordFactory(project=maintained_project, contributor=maintainer)
    publisher = UserFactory()
    MinistryPublisherFactory(user=publisher, ministry=maintained_project.ministry)
    publisher.is_verified = lambda: False

    with pytest.raises(InvalidSecondApproverError):
        verify(
            maintainer,
            record,
            VerificationStatus.ACCEPTED,
            "Attempted publisher approval",
            second_approval_by=publisher,
        )

    record.refresh_from_db()
    assert record.status == VerificationStatus.CANDIDATE
    assert (
        audits_for(record)
        .filter(actor=publisher, action="contribution.verify.denied", result="failure")
        .exists()
    )


@pytest.mark.unit
def test_only_accepted_records_can_be_revoked(maintainer, candidate):
    """REC-005: reversal targets accepted recognition only; double revoke is refused."""
    with pytest.raises(InvalidStatusTransitionError):
        revoke(SuperAdminFactory(), candidate, "nothing to reverse")

    verify(maintainer, candidate, VerificationStatus.ACCEPTED, "Accepted")
    revoke(SuperAdminFactory(), candidate, "Reversed once")
    with pytest.raises(InvalidStatusTransitionError):
        revoke(SuperAdminFactory(), candidate, "Reversed twice")


@pytest.mark.unit
def test_recognition_basis_is_accepted_records_only():
    """REC-001: candidates and rejected rows never count toward the verified portfolio."""
    member = UserFactory()
    accepted = ContributionRecordFactory(contributor=member)
    verify(
        ProjectMaintainerFactory(project=accepted.project).user,
        accepted,
        VerificationStatus.ACCEPTED,
        "Solid",
    )
    ContributionRecordFactory(contributor=member)
    rejected = ContributionRecordFactory(contributor=member)
    verify(
        ProjectMaintainerFactory(project=rejected.project).user,
        rejected,
        VerificationStatus.REJECTED,
        "Out of scope",
    )

    credited = list(accepted_contributions(member))
    assert credited == [accepted]
    assert link_profile_credit(accepted) is accepted


@pytest.mark.unit
def test_every_decision_writes_an_immutable_audit_row(maintainer, candidate):
    """SEC-008: accept and revoke both leave tamper-evident audit provenance."""
    verify(maintainer, candidate, VerificationStatus.ACCEPTED, "First decision")
    revoke(SuperAdminFactory(), candidate, "Second decision")

    actions = set(audits_for(candidate).values_list("action", flat=True))
    assert actions == {"contribution.accepted", "contribution.revoked"}
    entry = audits_for(candidate).first()
    entry.action = "contribution.tampered"
    with pytest.raises(PermissionError):
        entry.save()


@pytest.mark.unit
def test_non_code_evidence_is_credited_without_a_git_commit(maintained_project, maintainer):
    """REC-008/A6: accepted documentation work credits the right type with no provider event."""
    member = UserFactory()
    record = submit_evidence(
        member,
        maintained_project,
        Evidence(
            title="Administrator runbook",
            contribution_type=contribution_type("documentation"),
            evidence_url="https://example.com/runbook",
        ),
    )

    verify(maintainer, record, VerificationStatus.ACCEPTED, "Accurate and complete")

    credited = accepted_contributions(member).get()
    assert credited.contribution_type.slug == "documentation"
    assert credited.provider_event_ref == ""
    assert credited.source == ContributionSource.MEMBER_SUBMISSION
