import pytest
from django.urls import reverse

from apps.accounts.tests.factories import MemberProfileFactory
from apps.github_sync.tests.factories import GithubConnectionFactory

pytestmark = [pytest.mark.django_db]


def test_mem_005_public_profile_shows_only_consented_github_identity(client):
    """MEM-005/GIT-010: a public member page is the explicitly consented GitHub profile."""
    profile = MemberProfileFactory(
        headline="Internal DevNepal headline",
        bio="Internal DevNepal biography",
        directory_discoverable=True,
    )
    connection = GithubConnectionFactory(
        user=profile.user,
        login="kritika-gh",
        consent_scopes=["public_profile"],
        display_name="Kritika Poudel",
        avatar_url="https://avatars.githubusercontent.com/u/42?v=4",
        html_url="https://github.com/kritika-gh",
        bio="Open-source civic technologist",
        location="Kathmandu",
        company="Civic Lab",
        public_repos=12,
        followers=34,
    )

    response = client.get(
        reverse("accounts:public_profile", kwargs={"username": profile.user.username})
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert connection.display_name in content
    assert connection.avatar_url in content
    assert connection.html_url in content
    assert connection.bio in content
    assert "12 public repositories" in content
    assert "Internal DevNepal headline" not in content
    assert "Internal DevNepal biography" not in content
    assert "Verified contributions" not in content
    assert "Technical blogs" not in content


def test_mem_005_github_profile_is_hidden_without_public_profile_consent(client):
    """MEM-005/GIT-010: stored GitHub fields stay hidden when public-profile consent is absent."""
    profile = MemberProfileFactory(directory_discoverable=True)
    GithubConnectionFactory(
        user=profile.user,
        login="private-gh",
        consent_scopes=["read:user"],
        bio="Must not be public",
    )

    response = client.get(
        reverse("accounts:public_profile", kwargs={"username": profile.user.username})
    )

    assert response.status_code == 200
    assert "Must not be public" not in response.content.decode()
    assert "has not shared a GitHub profile" in response.content.decode()
