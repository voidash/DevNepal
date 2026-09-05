import pytest
from django.urls import reverse

from apps.contributions.enums import VerificationStatus
from apps.contributions.tests.factories import ContributionRecordFactory
from apps.ministries.tests.factories import UserFactory
from apps.projects.enums import ContributionMode, ProjectStatus
from apps.projects.tests.factories import ProjectFactory, ProjectMaintainerFactory

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.contributions.tests.urls"),
]


@pytest.mark.unit
def test_gov008_submission_explains_candidate_and_verification_boundary(client):
    """GOV-003/GOV-008/REC-008: non-code evidence enters the shared candidate review path."""
    member = UserFactory()
    project = ProjectFactory(
        status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
        contribution_mode=ContributionMode.OPEN_DIRECT,
    )
    client.force_login(member)

    response = client.get(reverse("contributions:submit", kwargs={"project_id": project.pk}))
    content = response.content.decode()

    assert response.status_code == 200
    assert "Submit evidence for verification" in content
    assert "Design, QA, documentation, translation, security, and research" in content
    assert "candidate record" in content
    assert "No score is created until a project maintainer accepts it" in content
    assert "Submit for verification" in content
    assert 'name="title"' in content
    assert 'name="contribution_type"' in content
    assert 'name="description"' in content
    assert 'name="evidence_url"' in content


@pytest.mark.unit
def test_git012_candidate_record_shows_provenance_status_and_next_step(client):
    """GIT-012/REC-001/REC-005: a candidate exposes provenance and the review boundary."""
    record = ContributionRecordFactory(
        title="Nepali aria-labels",
        evidence_url="https://example.com/evidence",
    )
    client.force_login(record.contributor)

    response = client.get(reverse("contributions:detail", kwargs={"contribution_id": record.pk}))
    content = response.content.decode()

    assert response.status_code == 200
    assert "Contribution record" in content
    assert "Candidate" in content
    assert "Awaiting verification by a project maintainer" in content
    assert "No score is created while this record is a candidate" in content
    assert record.get_source_display() in content
    assert reverse("contributions:history", kwargs={"contribution_id": record.pk}) in content


@pytest.mark.unit
def test_rec005_maintainer_review_presents_three_decisions_and_separation_of_duties(client):
    """GOV-008/REC-005/REC-008: maintainer review offers the three reasoned decisions."""
    record = ContributionRecordFactory(description="Keyboard-only walkthrough with 11 issues.")
    maintainer = ProjectMaintainerFactory(project=record.project).user
    client.force_login(maintainer)

    response = client.get(reverse("contributions:detail", kwargs={"contribution_id": record.pk}))
    content = response.content.decode()

    assert response.status_code == 200
    assert "Review evidence" in content
    assert "Accept" in content
    assert "Request clarification" in content
    assert "Reject" in content
    assert "A contributor cannot approve their own submitted evidence" in content
    assert "A reason is required for every decision" in content
    assert reverse("contributions:verify", kwargs={"contribution_id": record.pk}) in content


@pytest.mark.unit
def test_rec001_accepted_record_names_verifier_and_recognition_next_step(client):
    """REC-001/REC-005: accepted work names its verifier and links recognition history."""
    verifier = UserFactory(username="named-maintainer")
    record = ContributionRecordFactory(
        status=VerificationStatus.ACCEPTED,
        verified_by=verifier,
        verification_note="Reviewed and accepted",
    )
    client.force_login(record.contributor)

    response = client.get(reverse("contributions:detail", kwargs={"contribution_id": record.pk}))
    content = response.content.decode()

    assert response.status_code == 200
    assert "Accepted contribution" in content
    assert "Verified by" in content
    assert verifier.username in content
    assert "Recognition uses the scoring policy attached to this accepted record" in content
    assert reverse("recognition:my_profile") in content
