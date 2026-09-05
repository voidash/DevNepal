import pytest
from django.test import override_settings
from django.urls import reverse

from apps.contributions.enums import VerificationStatus
from apps.contributions.tests.factories import ContributionRecordFactory
from apps.ministries.tests.factories import SuperAdminFactory, UserFactory
from apps.recognition.models import ContributionScore
from apps.recognition.services import activate_policy
from apps.recognition.tests.factories import BadgeAwardFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def recognition_urlconf():
    """REC-003: use the mounted recognition routes for template flow checks."""
    with override_settings(ROOT_URLCONF="apps.recognition.tests.urls"):
        yield


@pytest.mark.unit
def test_rec003_private_recognition_explains_score_provenance_and_public_choice(client):
    """REC-001/REC-003/REC-004/REC-007: private history explains scoring and display control."""
    member = UserFactory()
    policy = activate_policy(SuperAdminFactory(), {"standard": 12})
    contribution = ContributionRecordFactory(
        contributor=member,
        status=VerificationStatus.ACCEPTED,
    )
    ContributionScore.objects.create(contribution=contribution, policy=policy, points=12)
    BadgeAwardFactory(recipient=member, contribution=contribution)
    client.force_login(member)

    response = client.get(reverse("recognition:my_profile"))
    content = response.content.decode()

    assert response.status_code == 200
    assert "Your recognition" in content
    assert "Verified, accepted work only" in content
    assert "Every score names the policy version" in content
    assert "Public leaderboard display is your choice" in content
    assert "12 points" in content
    assert "policy v" in content
    assert reverse("accounts:profile_edit") in content


@pytest.mark.unit
@override_settings(RECOGNITION_ENABLED=True)
def test_rec003_public_leaderboard_explains_what_counts_and_what_does_not(client):
    """REC-001/REC-002/REC-003/REC-008: rankings publish their verification boundary."""
    member = UserFactory(username="ranked-member")
    policy = activate_policy(SuperAdminFactory(), {"standard": 12})
    contribution = ContributionRecordFactory(
        contributor=member,
        status=VerificationStatus.ACCEPTED,
    )
    ContributionScore.objects.create(contribution=contribution, policy=policy, points=12)

    response = client.get(reverse("recognition:leaderboard"))
    content = response.content.decode()

    assert response.status_code == 200
    assert '<h1 id="leaderboard-heading">Recognition</h1>' in content
    assert "verified, accepted contributions" in content
    assert "Commits, bot events, and self-reported activity are not scored" in content
    assert "Design, QA, documentation, translation, security, and research count" in content
    assert member.username in content
    assert "12 points" in content
