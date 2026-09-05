import pytest

from apps.contributions.enums import ContributionSource, VerificationStatus
from apps.contributions.services import Evidence, InvalidEvidenceError, submit_evidence
from apps.contributions.tests.factories import contribution_type
from apps.projects.enums import ContributionMode, ProjectStatus
from apps.projects.tests.factories import ProjectFactory, UserFactory
from apps.taxonomy.enums import TermVocabulary
from apps.taxonomy.tests.factories import TaxonomyTermFactory

pytestmark = [pytest.mark.django_db]


@pytest.mark.unit
def test_submitted_evidence_is_candidate_not_verification():
    """BR-006: self-submission alone is evidence; the record starts unverified."""
    member = UserFactory()
    project = ProjectFactory(
        status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
        contribution_mode=ContributionMode.OPEN_DIRECT,
    )

    record = submit_evidence(
        member,
        project,
        Evidence(
            title="Nepali dashboard translation sprint",
            contribution_type=contribution_type("localization"),
            description="Translated 40 strings for the citizen dashboard.",
            evidence_url="https://github.com/moit/service-directory/pull/12",
        ),
    )

    assert record.contributor == member
    assert record.project == project
    assert record.source == ContributionSource.MEMBER_SUBMISSION
    assert record.status == VerificationStatus.CANDIDATE
    assert record.verified_by is None
    assert record.verified_at is None
    assert record.contribution_type.slug == "localization"


@pytest.mark.unit
def test_evidence_requires_an_approved_contribution_category():
    """GOV-008/A6: evidence must target an active CONTRIBUTION_TYPE term."""
    member = UserFactory()
    project = ProjectFactory()
    wrong_vocabulary = TaxonomyTermFactory(vocabulary=TermVocabulary.TECHNOLOGY)
    inactive = TaxonomyTermFactory(
        vocabulary=TermVocabulary.CONTRIBUTION_TYPE, label="Legacy", slug="legacy", is_active=False
    )

    with pytest.raises(InvalidEvidenceError):
        submit_evidence(member, project, Evidence(title="X", contribution_type=wrong_vocabulary))
    with pytest.raises(InvalidEvidenceError):
        submit_evidence(member, project, Evidence(title="X", contribution_type=inactive))


@pytest.mark.unit
def test_evidence_requires_title_and_active_member():
    """BR-006: incomplete evidence is refused at the service boundary."""
    project = ProjectFactory()

    with pytest.raises(InvalidEvidenceError):
        submit_evidence(
            UserFactory(), project, Evidence(title="   ", contribution_type=contribution_type("qa"))
        )
    inactive = UserFactory(is_active=False)
    with pytest.raises(InvalidEvidenceError):
        submit_evidence(
            inactive, project, Evidence(title="Title", contribution_type=contribution_type("qa"))
        )
    assert project.contributions.count() == 0
