import pytest

from apps.github_sync.models import (
    GithubIssueSnapshot,
    GithubPullRequestSnapshot,
    GithubRepositoryContributor,
)
from apps.github_sync.services import (
    refresh_github_public_profile,
    refresh_public_repository_snapshot,
)
from apps.github_sync.tests.factories import GithubConnectionFactory, RepositoryConnectionFactory

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


class SnapshotClient:
    def repository_metadata(self, installation_id, full_name):
        return {"full_name": full_name, "private": False, "default_branch": "main"}

    def list_open_issues(self, installation_id, full_name):
        return [
            {
                "id": 1,
                "number": 4,
                "title": "Translate form",
                "body": "Public body",
                "state": "open",
                "comments": 3,
                "html_url": f"https://github.com/{full_name}/issues/4",
                "updated_at": "2026-09-05T10:00:00Z",
                "user": {
                    "login": "voidash",
                    "avatar_url": "https://avatars.githubusercontent.com/u/1",
                },
                "labels": [{"name": "good first issue"}],
            }
        ]

    def list_open_pull_requests(self, installation_id, full_name):
        return [
            {
                "id": 2,
                "number": 5,
                "title": "Fix contrast",
                "body": "Public PR body",
                "state": "open",
                "comments": 2,
                "html_url": f"https://github.com/{full_name}/pull/5",
                "updated_at": "2026-09-05T10:00:00Z",
                "user": {
                    "login": "voidash",
                    "avatar_url": "https://avatars.githubusercontent.com/u/1",
                },
            }
        ]

    def list_contributors(self, installation_id, full_name):
        return [
            {
                "id": 1,
                "login": "voidash",
                "avatar_url": "https://avatars.githubusercontent.com/u/1",
                "html_url": "https://github.com/voidash",
                "contributions": 9,
            }
        ]


def test_public_repository_sync_persists_bounded_public_issue_pr_and_contributor_snapshots():
    """GIT-003/GIT-010: only a public repository receives bounded public GitHub snapshots."""
    connection = RepositoryConnectionFactory(is_public=True)

    result = refresh_public_repository_snapshot(connection, SnapshotClient())

    assert result.issues == 1
    assert result.pull_requests == 1
    assert result.contributors == 1
    assert GithubIssueSnapshot.objects.get(repository=connection).body == "Public body"
    assert GithubPullRequestSnapshot.objects.get(repository=connection).author_login == "voidash"
    assert GithubRepositoryContributor.objects.get(repository=connection).contributions == 9


def test_public_repository_sync_never_fetches_private_repository_data():
    """GIT-010: private repository snapshots are blocked before every provider call."""
    connection = RepositoryConnectionFactory(is_public=False)

    result = refresh_public_repository_snapshot(connection, SnapshotClient())

    assert result.issues == result.pull_requests == result.contributors == 0
    assert not GithubIssueSnapshot.objects.filter(repository=connection).exists()


def test_public_profile_sync_requires_explicit_profile_consent():
    """GIT-002/GIT-010: an unconsented GitHub profile is never fetched or stored."""
    connection = GithubConnectionFactory(consent_scopes=[])

    assert refresh_github_public_profile(connection, SnapshotClient()) is False
    connection.refresh_from_db()
    assert connection.public_profile_fetched_at is None
