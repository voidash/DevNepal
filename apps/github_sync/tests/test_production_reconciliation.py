import pytest
from django.test import override_settings

from apps.github_sync.errors import ReconciliationError
from apps.github_sync.services import GithubReconciliationFetcher
from apps.github_sync.tests.factories import RepositoryConnectionFactory

pytestmark = [pytest.mark.unit, pytest.mark.github_webhook, pytest.mark.django_db]


class StubClient:
    def __init__(self, events):
        self.events = events
        self.calls = []

    def list_repository_events_page(self, installation_id, full_name, page):
        self.calls.append((installation_id, full_name, page))
        return self.events


def pull_request_event(connection, *, branch="main"):
    return {
        "id": "991",
        "type": "PullRequestEvent",
        "actor": {"login": "member", "type": "User"},
        "repo": {"name": connection.full_name},
        "payload": {
            "action": "closed",
            "pull_request": {
                "id": 771,
                "number": 9,
                "merged": True,
                "user": {"login": "author", "type": "User"},
                "base": {"ref": branch},
            },
        },
    }


def test_fetcher_maps_provider_api_event_and_advances_page_cursor():
    """GIT-006/GIT-007: production fetcher normalizes API events for the ledger."""
    connection = RepositoryConnectionFactory()
    connection.project.default_branch = "main"
    connection.project.save(update_fields=["default_branch"])
    client = StubClient([pull_request_event(connection)])

    page = GithubReconciliationFetcher(client=client).fetch(connection, "", None)

    assert client.calls == [(connection.installation_id, connection.full_name, 1)]
    assert len(page.events) == 1
    assert page.events[0].parsed_event.event_id == "771"
    assert page.next_cursor == ""


def test_fetcher_rejects_missing_configured_default_branch_before_api_call():
    """GIT-006/GIT-007: an unsafe project branch configuration never reaches GitHub."""
    connection = RepositoryConnectionFactory()
    connection.project.default_branch = ""
    connection.project.save(update_fields=["default_branch"])
    client = StubClient([])

    with pytest.raises(ReconciliationError, match="default branch"):
        GithubReconciliationFetcher(client=client).fetch(connection, "", None)
    assert client.calls == []


def test_fetcher_ignores_events_targeting_a_non_default_branch():
    """GIT-007: PR activity outside the configured default branch is not ingested."""
    connection = RepositoryConnectionFactory()
    connection.project.default_branch = "main"
    connection.project.save(update_fields=["default_branch"])
    client = StubClient([pull_request_event(connection, branch="release")])

    page = GithubReconciliationFetcher(client=client).fetch(connection, "", None)

    assert page.events == ()


@override_settings(GITHUB_VERIFIED_EVENT_TYPES=("release",))
def test_fetcher_honors_configured_verified_event_allowlist():
    """GIT-007: deployment event configuration is enforced before ledger ingestion."""
    connection = RepositoryConnectionFactory()
    connection.project.default_branch = "main"
    connection.project.save(update_fields=["default_branch"])
    client = StubClient([pull_request_event(connection)])

    page = GithubReconciliationFetcher(client=client).fetch(connection, "", None)

    assert page.events == ()
