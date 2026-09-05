import pytest
from django.urls import reverse
from django.utils import translation

from apps.github_sync.models import GithubPublicProfileSnapshot, GithubRepositoryContributor
from apps.github_sync.tests.factories import RepositoryConnectionFactory
from apps.projects.enums import ProjectStatus

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def test_git_010_public_github_profile_uses_provider_data_and_tracked_repository_activity(client):
    """GIT-010: the in-app contributor profile shows public GitHub facts and tracked work."""
    profile = GithubPublicProfileSnapshot.objects.create(
        github_user_id=1,
        login="voidash",
        avatar_url="https://avatars.githubusercontent.com/u/1",
        html_url="https://github.com/voidash",
        display_name="Voidash Maintainer",
        bio="Maintains open civic software.",
        location="Nepal",
        company="Open source",
        public_repos=12,
        followers=34,
    )
    repository = RepositoryConnectionFactory(
        full_name="voidash/civic-help-directory",
        is_public=True,
        deactivated_at=None,
        project__status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
    )
    GithubRepositoryContributor.objects.create(
        repository=repository,
        github_user_id=profile.github_user_id,
        login=profile.login,
        avatar_url=profile.avatar_url,
        profile_url=profile.html_url,
        contributions=9,
    )
    GithubPublicProfileSnapshot.objects.create(
        github_user_id=2,
        login="iamtekson",
        html_url="https://github.com/iamtekson",
        display_name="Tek Kshetri",
        location="Nepal",
        followers=936,
    )
    GithubPublicProfileSnapshot.objects.create(
        github_user_id=3,
        login="hemantapkh",
        html_url="https://github.com/hemantapkh",
        display_name="Hemanta Pokharel",
        location="Kathmandu, Nepal",
        followers=2686,
    )

    response = client.get(reverse("github_sync_public:public_profile", args=[profile.login]))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Voidash Maintainer" in content
    assert "Maintains open civic software." in content
    assert "12 public repositories" in content
    assert "34 followers" in content
    assert "civic-help-directory" in content
    assert "9 commits" in content
    assert profile.html_url in content
    assert "Public information from GitHub" in content
    assert "Last synchronized" in content
    assert "This profile uses public information from GitHub." in content
    assert "It does not create or require a DevNepal account." in content
    assert "More GitHub profiles" in content
    assert "Tek Kshetri" in content
    assert "Hemanta Pokharel" in content
    assert "iamtekson" in content
    assert "hemantapkh" in content
    assert "Skills" not in content
    assert "Badges" not in content
    assert "Verified contributions" not in content
    assert content.count("<main") == 1


def test_git_010_unknown_public_github_profile_is_not_invented(client):
    """GIT-010: DevNepal returns 404 rather than inventing an unsynced GitHub identity."""
    response = client.get(reverse("github_sync_public:public_profile", args=["unknown-person"]))

    assert response.status_code == 404


def test_git_010_localized_profile_route_preserves_the_selected_language(client):
    """GIT-010: public project links keep the active language on GitHub profiles."""
    profile = GithubPublicProfileSnapshot.objects.create(
        github_user_id=2,
        login="nepali-contributor",
        html_url="https://github.com/nepali-contributor",
    )

    with translation.override("ne"):
        profile_url = reverse(
            "github_sync_public:public_profile",
            args=[profile.login],
        )
    response = client.get(profile_url)

    assert profile_url.startswith("/ne/")
    assert response.status_code == 200
    assert response.wsgi_request.LANGUAGE_CODE == "ne"
