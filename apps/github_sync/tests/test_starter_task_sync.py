import pytest

from apps.github_sync.errors import GithubAppResponseError
from apps.github_sync.models import GithubStarterTask
from apps.github_sync.services import refresh_starter_tasks
from apps.github_sync.tests.factories import RepositoryConnectionFactory

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


class RecordingClient:
    def __init__(self, payload=None, error=None):
        self.payload = payload or []
        self.error = error
        self.calls = []

    def list_open_issues(self, installation_id, full_name):
        self.calls.append((installation_id, full_name))
        if self.error:
            raise self.error
        return self.payload


def issue(*, issue_id=101, number=21, title="Add Nepali labels", labels=None, url=None):
    return {
        "id": issue_id,
        "number": number,
        "title": title,
        "labels": labels if labels is not None else [{"name": "good first issue"}],
        "html_url": url or f"https://github.com/doit-np/sewa-portal/issues/{number}",
        "updated_at": "2026-09-05T10:30:00Z",
    }


def test_sync_persists_only_labelled_issue_metadata_and_removes_stale_rows():
    """DSC-009/GIT-010: public starter snapshots retain selected labels, never bodies or PRs."""
    connection = RepositoryConnectionFactory(full_name="doit-np/sewa-portal", is_public=True)
    stale = GithubStarterTask.objects.create(
        repository=connection,
        github_issue_id=99,
        number=9,
        title="Old task",
        url="https://github.com/doit-np/sewa-portal/issues/9",
        labels=["help wanted"],
    )
    client = RecordingClient(
        [
            issue(),
            issue(issue_id=102, number=22, labels=[{"name": "bug"}]),
            {**issue(issue_id=103, number=23), "pull_request": {"url": "hidden"}},
        ]
    )

    result = refresh_starter_tasks(connection, client)

    assert result.stored == 1
    assert result.ignored == 2
    assert client.calls == [(connection.installation_id, connection.full_name)]
    assert not GithubStarterTask.objects.filter(pk=stale.pk).exists()
    task = GithubStarterTask.objects.get(repository=connection, github_issue_id=101)
    assert task.number == 21
    assert task.title == "Add Nepali labels"
    assert task.labels == ["good first issue"]
    assert task.url == "https://github.com/doit-np/sewa-portal/issues/21"
    connection.refresh_from_db()
    assert connection.task_snapshot_at is not None
    assert connection.task_snapshot_note == ""


def test_sync_never_fetches_or_exposes_private_or_unlinked_repositories():
    """GIT-010: a private or unlinked repository cannot produce a public task snapshot."""
    private_connection = RepositoryConnectionFactory(is_public=False)
    unlinked_connection = RepositoryConnectionFactory(is_public=True, project=None)
    client = RecordingClient([issue()])

    private_result = refresh_starter_tasks(private_connection, client)
    unlinked_result = refresh_starter_tasks(unlinked_connection, client)

    assert private_result.stored == 0
    assert unlinked_result.stored == 0
    assert client.calls == []
    assert not GithubStarterTask.objects.filter(
        repository__in=[private_connection, unlinked_connection]
    ).exists()


def test_sync_records_provider_failure_for_honest_public_freshness_state():
    """DSC-009/GIT-001: task-sync failure is persisted, logged by the caller, and propagated."""
    connection = RepositoryConnectionFactory(is_public=True)

    with pytest.raises(GithubAppResponseError):
        refresh_starter_tasks(connection, RecordingClient(error=GithubAppResponseError("down")))

    connection.refresh_from_db()
    assert connection.task_snapshot_at is None
    assert connection.task_snapshot_note == "GitHub starter-task snapshot could not be refreshed."
