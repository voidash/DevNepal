"""A6 — Non-code evidence → maintainer acceptance → correct type credit, no Git commit."""

import pytest

from apps.contributions.enums import ContributionSource, VerificationStatus
from apps.contributions.services import (
    Evidence,
    SelfApprovalError,
    accepted_contributions,
    submit_evidence,
    verify,
)
from apps.contributions.tests.factories import contribution_type
from apps.ministries.tests.factories import MinistryPublisherFactory
from apps.projects.enums import ContributionMode, ProjectStatus
from apps.projects.tests.factories import ProjectFactory, ProjectMaintainerFactory, UserFactory

pytestmark = [pytest.mark.django_db, pytest.mark.acceptance]


def test_a06_noncode_evidence_acceptance_credits_type_without_commit():
    """A6/GOV-008/BR-006/REC-008: evidence→acceptance→correct non-code type, no provider event."""
    project = ProjectFactory(
        status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
        contribution_mode=ContributionMode.OPEN_DIRECT,
    )
    maintainer = ProjectMaintainerFactory(project=project).user
    member = UserFactory()

    record = submit_evidence(
        member,
        project,
        Evidence(
            title="Citizen dashboard usability study",
            contribution_type=contribution_type("research"),
            description="Interviewed 12 citizens across three provinces.",
            evidence_url="https://example.com/research/usability-2026",
        ),
    )
    assert record.status == VerificationStatus.CANDIDATE
    assert record.source == ContributionSource.MEMBER_SUBMISSION

    verify(maintainer, record, VerificationStatus.ACCEPTED, "Rigorous and actionable")

    credited = accepted_contributions(member).get()
    assert credited.contribution_type.slug == "research"
    assert credited.provider_event_ref == ""
    assert credited.verified_at is not None


def test_a06_self_award_path_requires_secondary_approval():
    """A6/BR-007: a maintainer accepting their own non-code evidence needs a second approver."""
    project = ProjectFactory(
        status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
        contribution_mode=ContributionMode.OPEN_DIRECT,
    )
    maintainer = ProjectMaintainerFactory(project=project).user
    own_record = submit_evidence(
        maintainer,
        project,
        Evidence(title="Own design system audit", contribution_type=contribution_type("uiux")),
    )

    with pytest.raises(SelfApprovalError):
        verify(maintainer, own_record, VerificationStatus.ACCEPTED, "my own work")

    second = MinistryPublisherFactory(ministry=project.ministry).user
    verified = verify(
        maintainer,
        own_record,
        VerificationStatus.ACCEPTED,
        "Publisher countersigned",
        second_approval_by=second,
    )
    assert verified.status == VerificationStatus.ACCEPTED
    assert verified.secondary_approval_by == second
