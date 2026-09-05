import pytest
from django.test import override_settings

from apps.audit.models import AuditEvent
from apps.contributions.enums import ContributionSource, VerificationStatus
from apps.contributions.services import (
    Evidence,
    InvalidDecisionError,
    InvalidSecondApproverError,
    InvalidStatusTransitionError,
    MissingReasonError,
    SelfApprovalError,
    UnauthorizedRevokerError,
    UnauthorizedVerifierError,
    accepted_contributions,
    link_profile_credit,
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
