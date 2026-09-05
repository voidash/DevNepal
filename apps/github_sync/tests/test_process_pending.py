import json
import sys
import types

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.github_sync.enums import ProcessingState
from apps.github_sync.errors import GithubAppResponseError
from apps.github_sync.models import (
    GithubIssueSnapshot,
    GithubPullRequestSnapshot,
    ProviderEvent,
    RepositoryConnection,
)
from apps.github_sync.services import ingest_webhook, process_pending
from apps.github_sync.tests.factories import (
    WEBHOOK_SECRET,
    ProviderEventFactory,
    RepositoryConnectionFactory,
    parsed_payload,
    pr_merged_body,
    sign_body,
)
from apps.github_sync.webhooks import ParsedEvent

pytestmark = [pytest.mark.integration, pytest.mark.github_webhook, pytest.mark.django_db]


def install_fake_contributions(monkeypatch, calls):
    module = types.ModuleType("apps.contributions.services")

    def record_candidate_from_github(parsed, project):
        calls.append((parsed, project))

    module.record_candidate_from_github = record_candidate_from_github
    monkeypatch.setitem(sys.modules, "apps.contributions.services", module)


def block_contributions(monkeypatch):
    monkeypatch.setitem(sys.modules, "apps.contributions.services", None)


def ingest_pending(delivery_id, *, node_id="R_kgDOKExAmPlE", pr_id=987654):
    from apps.github_sync.services import ingest_webhook

    body = pr_merged_body(node_id=node_id, pr_id=pr_id)
    return ingest_webhook(
        "github",
        "pull_request",
        delivery_id,
        sign_body(body),
        timezone.now().isoformat(),
        body,
    )


def issue_lifecycle_body(action, *, node_id, issue_id=8080, number=12):
    return json.dumps(
        {
            "action": action,
            "issue": {
                "id": issue_id,
                "number": number,
                "state": "closed" if action == "closed" else "open",
                "state_reason": "not_planned" if action == "closed" else None,
            },
            "repository": {
                "id": 555001,
                "node_id": node_id,
                "name": "gov-portal",
            },
            "sender": {"login": "sita", "type": "User"},
        }
    ).encode("utf-8")


def pull_request_lifecycle_body(action, *, node_id, pull_request_id=9090, number=34):
    return json.dumps(
        {
            "action": action,
            "pull_request": {
                "id": pull_request_id,
                "number": number,
                "merged": False,
                "user": {"login": "sita", "type": "User"},
                "base": {"ref": "main"},
            },
            "repository": {
                "id": 555001,
                "node_id": node_id,
                "name": "gov-portal",
            },
            "sender": {"login": "sita", "type": "User"},
        }
    ).encode("utf-8")


def issue_comment_lifecycle_body(action, *, node_id, comment_id=10101, issue_id=8080, number=12):
    return json.dumps(
        {
            "action": action,
            "comment": {"id": comment_id, "body": "Public status update"},
            "issue": {"id": issue_id, "number": number, "state": "open"},
            "repository": {
                "id": 555001,
                "node_id": node_id,
                "name": "gov-portal",
            },
            "sender": {"login": "sita", "type": "User"},
        }
    ).encode("utf-8")


class LifecycleSnapshotClient:
    def __init__(self):
        self.calls = []

    def repository_metadata(self, installation_id, full_name):
        self.calls.append((installation_id, full_name))
        return {"full_name": full_name, "private": False, "default_branch": "main"}

    def list_open_issues(self, installation_id, full_name):
        return [
            {
                "id": 8080,
                "number": 12,
                "title": "New public issue",
                "body": "Created after the last manual refresh",
                "state": "open",
                "comments": 0,
                "html_url": f"https://github.com/{full_name}/issues/12",
                "updated_at": "2026-09-06T10:00:00Z",
                "user": {
                    "login": "voidash",
                    "avatar_url": "https://avatars.githubusercontent.com/u/1",
                },
                "labels": [{"name": "help wanted"}],
            }
        ]

    def list_open_pull_requests(self, installation_id, full_name):
        return [
            {
                "id": 9090,
                "number": 34,
                "title": "Fresh public pull request",
                "body": "Ready for ministry review",
                "state": "open",
                "comments": 0,
                "html_url": f"https://github.com/{full_name}/pull/34",
                "updated_at": "2026-09-06T10:00:00Z",
                "user": {
                    "login": "sita",
                    "avatar_url": "https://avatars.githubusercontent.com/u/2",
                },
                "labels": [{"name": "ready for review"}],
            }
        ]

    def list_contributors(self, installation_id, full_name):
        return []


class FailingLifecycleSnapshotClient(LifecycleSnapshotClient):
    def repository_metadata(self, installation_id, full_name):
        raise GithubAppResponseError("provider unavailable")


class TestProcessPending:
    @override_settings(GITHUB_WEBHOOK_SECRET=WEBHOOK_SECRET)
    def test_inflight_repository_refresh_coalesces_without_another_provider_call(self, monkeypatch):
        """GIT-003/SEC-006: a webhook burst cannot multiply full provider snapshots."""
        connection = RepositoryConnectionFactory(
            is_public=True, repository_node_id="R_kgDOInflightCoalesce"
        )
        client = LifecycleSnapshotClient()
        monkeypatch.setattr("apps.github_sync.services.github_app_client", lambda: client)
        monkeypatch.setattr("apps.github_sync.services.cache.add", lambda *args, **kwargs: False)
        body = issue_lifecycle_body("labeled", node_id=connection.repository_node_id)
        event = ingest_webhook("github", "issues", "inflight-coalesce", sign_body(body), None, body)

        result = process_pending(limit=10)

        event.refresh_from_db()
        assert result.blocked == 1
        assert event.processing_state == ProcessingState.PENDING
        assert client.calls == []

    @pytest.mark.parametrize(
        "action",
        ["opened", "edited", "reopened", "closed", "labeled", "unlabeled", "deleted"],
    )
    @override_settings(GITHUB_WEBHOOK_SECRET=WEBHOOK_SECRET)
    def test_signed_issue_lifecycle_refreshes_public_snapshot_in_worker(self, monkeypatch, action):
        """GIT-003/GIT-004/GIT-005/GIT-010: signed issue changes refresh the public cache."""
        connection = RepositoryConnectionFactory(
            is_public=True, repository_node_id="R_kgDOIssueLifecycle"
        )
        client = LifecycleSnapshotClient()
        monkeypatch.setattr("apps.github_sync.services.github_app_client", lambda: client)
        body = issue_lifecycle_body(action, node_id=connection.repository_node_id)

        event = ingest_webhook(
            "github",
            "issues",
            f"issue-lifecycle-{action}",
            sign_body(body),
            timezone.now().isoformat(),
            body,
        )
        duplicate = ingest_webhook(
            "github",
            "issues",
            f"issue-lifecycle-{action}",
            sign_body(body),
            timezone.now().isoformat(),
            body,
        )

        assert event.processing_state == ProcessingState.PENDING
        assert duplicate.pk == event.pk
        assert client.calls == []
        assert not GithubIssueSnapshot.objects.filter(repository=connection).exists()

        result = process_pending(limit=10)

        event.refresh_from_db()
        assert result.processed == 1
        assert event.processing_state == ProcessingState.PROCESSED
        assert event.last_error == ""
        assert GithubIssueSnapshot.objects.get(repository=connection).title == "New public issue"

    @pytest.mark.parametrize(
        "action",
        [
            "opened",
            "edited",
            "reopened",
            "closed",
            "ready_for_review",
            "converted_to_draft",
            "labeled",
            "unlabeled",
        ],
    )
    @override_settings(GITHUB_WEBHOOK_SECRET=WEBHOOK_SECRET)
    def test_signed_pull_request_lifecycle_refreshes_public_snapshot_in_worker(
        self, monkeypatch, action
    ):
        """GIT-003/GIT-004/GIT-005: signed pull-request changes refresh public projections."""
        connection = RepositoryConnectionFactory(
            is_public=True, repository_node_id="R_kgDOPullRequestLifecycle"
        )
        client = LifecycleSnapshotClient()
        monkeypatch.setattr("apps.github_sync.services.github_app_client", lambda: client)
        body = pull_request_lifecycle_body(action, node_id=connection.repository_node_id)

        event = ingest_webhook(
            "github",
            "pull_request",
            f"pull-request-lifecycle-{action}",
            sign_body(body),
            timezone.now().isoformat(),
            body,
        )

        result = process_pending(limit=10)

        event.refresh_from_db()
        assert result.processed == 1
        assert event.processing_state == ProcessingState.PROCESSED
        assert event.last_error == ""
        assert GithubPullRequestSnapshot.objects.get(repository=connection).title == (
            "Fresh public pull request"
        )

    @pytest.mark.parametrize("action", ["created", "edited", "deleted"])
    @override_settings(GITHUB_WEBHOOK_SECRET=WEBHOOK_SECRET)
    def test_signed_issue_comment_lifecycle_refreshes_public_snapshot_in_worker(
        self, monkeypatch, action
    ):
        """GIT-003/GIT-004/GIT-005: issue comments refresh public issue comment counts."""
        connection = RepositoryConnectionFactory(
            is_public=True, repository_node_id="R_kgDOIssueCommentLifecycle"
        )
        client = LifecycleSnapshotClient()
        monkeypatch.setattr("apps.github_sync.services.github_app_client", lambda: client)
        body = issue_comment_lifecycle_body(action, node_id=connection.repository_node_id)

        event = ingest_webhook(
            "github",
            "issue_comment",
            f"issue-comment-lifecycle-{action}",
            sign_body(body),
            timezone.now().isoformat(),
            body,
        )

        result = process_pending(limit=10)

        event.refresh_from_db()
        assert result.processed == 1
        assert event.processing_state == ProcessingState.PROCESSED
        assert GithubIssueSnapshot.objects.get(repository=connection).comments_count == 0

    @override_settings(GITHUB_WEBHOOK_SECRET=WEBHOOK_SECRET)
    def test_newer_projection_coalesces_older_pending_lifecycle_event(self, monkeypatch):
        """GIT-003/GIT-005: one completed projection satisfies an older pending delivery."""
        connection = RepositoryConnectionFactory(
            is_public=True, repository_node_id="R_kgDOProjectionCoalesce"
        )
        client = LifecycleSnapshotClient()
        monkeypatch.setattr("apps.github_sync.services.github_app_client", lambda: client)
        first_body = issue_lifecycle_body("opened", node_id=connection.repository_node_id)
        second_body = issue_lifecycle_body(
            "edited", node_id=connection.repository_node_id, issue_id=8081
        )
        first = ingest_webhook(
            "github", "issues", "coalesce-first", sign_body(first_body), None, first_body
        )
        second = ingest_webhook(
            "github", "issues", "coalesce-second", sign_body(second_body), None, second_body
        )

        result = process_pending(limit=10)

        first.refresh_from_db()
        second.refresh_from_db()
        assert result.processed == 2
        assert first.processing_state == second.processing_state == ProcessingState.PROCESSED
        assert client.calls == [(connection.installation_id, connection.full_name)]

    @override_settings(GITHUB_WEBHOOK_SECRET=WEBHOOK_SECRET)
    def test_merged_pull_request_refreshes_projection_without_skipping_contribution_credit(
        self, monkeypatch
    ):
        """GIT-003/GIT-005/GIT-007: merged PRs refresh the cache and retain credit ledger work."""
        connection = RepositoryConnectionFactory(
            is_public=True, repository_node_id="R_kgDOMergedPullRequest"
        )
        client = LifecycleSnapshotClient()
        calls = []
        install_fake_contributions(monkeypatch, calls)
        monkeypatch.setattr("apps.github_sync.services.github_app_client", lambda: client)
        body = pr_merged_body(node_id=connection.repository_node_id)

        event = ingest_webhook(
            "github",
            "pull_request",
            "merged-pull-request-refresh",
            sign_body(body),
            timezone.now().isoformat(),
            body,
        )

        result = process_pending(limit=10)

        event.refresh_from_db()
        assert result.processed == 1
        assert event.processing_state == ProcessingState.PROCESSED
        assert len(calls) == 1
        assert calls[0][1] == connection.project
        assert GithubPullRequestSnapshot.objects.get(repository=connection).number == 34

    @override_settings(GITHUB_WEBHOOK_SECRET=WEBHOOK_SECRET)
    def test_issue_lifecycle_snapshot_failure_keeps_last_good_projection(self, monkeypatch):
        """GIT-005/GIT-010: provider failure retains the public cache and accepts the delivery."""
        connection = RepositoryConnectionFactory(
            is_public=True, repository_node_id="R_kgDOIssueFailure"
        )
        old_issue = GithubIssueSnapshot.objects.create(
            repository=connection,
            github_issue_id=99,
            number=99,
            title="Last known public issue",
            state="open",
            url=f"https://github.com/{connection.full_name}/issues/99",
        )
        monkeypatch.setattr(
            "apps.github_sync.services.github_app_client", FailingLifecycleSnapshotClient
        )
        body = issue_lifecycle_body("opened", node_id=connection.repository_node_id)
        event = ingest_webhook(
            "github",
            "issues",
            "issue-lifecycle-failure",
            sign_body(body),
            timezone.now().isoformat(),
            body,
        )

        result = process_pending(limit=10)

        event.refresh_from_db()
        connection.refresh_from_db()
        assert result.blocked == 1
        assert event.processing_state == ProcessingState.PENDING
        assert event.last_error == "retry: GitHub public snapshot refresh unavailable"
        assert GithubIssueSnapshot.objects.filter(pk=old_issue.pk).exists()
        assert connection.public_snapshot_note

    def test_unmapped_repository_fails_without_side_effects(self, monkeypatch):
        """GIT-005: events for unmapped repositories fail loudly, never crediting."""
        calls = []
        install_fake_contributions(monkeypatch, calls)
        event = ProviderEventFactory()
        RepositoryConnection.objects.all().delete()

        result = process_pending(limit=10)

        event.refresh_from_db()
        assert event.processing_state == ProcessingState.FAILED
        assert "not mapped" in event.last_error
        assert event.processing_attempts == 1
        assert result.failed == 1
        assert calls == []

    def test_missing_contributions_service_leaves_event_pending(self, monkeypatch):
        """GIT-005: a mid-flight contributions app never loses queued events."""
        block_contributions(monkeypatch)
        event = ProviderEventFactory()

        result = process_pending(limit=10)

        event.refresh_from_db()
        assert event.processing_state == ProcessingState.PENDING
        assert event.processing_attempts == 0
        assert result.processed == 0
        assert result.failed == 0
        assert result.blocked == 1
        assert result.blocked_event_ids == [str(event.pk)]

    def test_mapped_event_processes_once_into_contributions(self, monkeypatch):
        """GIT-005/A5: a mapped PENDING event becomes PROCESSED with exactly one record call."""
        calls = []
        install_fake_contributions(monkeypatch, calls)
        event = ProviderEventFactory()

        result = process_pending(limit=10)

        event.refresh_from_db()
        assert result.processed == 1
        assert event.processing_state == ProcessingState.PROCESSED
        assert event.processed_at is not None
        assert event.processing_attempts == 1
        assert len(calls) == 1
        parsed, project = calls[0]
        assert isinstance(parsed, ParsedEvent)
        assert parsed.event_id == event.payload["event_id"]
        assert parsed.repository_node_id == event.payload["repository_node_id"]
        assert project == event.repository.project

    def test_rerun_never_duplicates_contributions(self, monkeypatch):
        """GIT-005/A5: re-running the worker over processed events creates no duplicates."""
        calls = []
        install_fake_contributions(monkeypatch, calls)
        ProviderEventFactory()

        process_pending(limit=10)
        process_pending(limit=10)
        process_pending(limit=10)

        assert len(calls) == 1

    def test_bot_actor_is_processed_without_credit(self, monkeypatch):
        """GIT-008: bot actors are filtered in github_sync before any contribution record."""
        calls = []
        install_fake_contributions(monkeypatch, calls)
        payload = parsed_payload(
            node_id="R_kgDOBotNode001",
            event_id=555001,
            is_bot=True,
            login="dependabot[bot]",
        )
        event = ProviderEventFactory(
            payload=payload,
            node_id="R_kgDOBotNode001",
            event_id=555001,
        )

        result = process_pending(limit=10)

        event.refresh_from_db()
        assert result.processed == 1
        assert event.processing_state == ProcessingState.PROCESSED
        assert "bot" in event.last_error
        assert calls == []

    def test_connection_without_project_fails(self, monkeypatch):
        """GIT-005: a repository connection with no listed project cannot credit anything."""
        calls = []
        install_fake_contributions(monkeypatch, calls)
        connection = RepositoryConnectionFactory(project=None)
        event = ProviderEventFactory(node_id=connection.repository_node_id)

        result = process_pending(limit=10)

        event.refresh_from_db()
        assert event.processing_state == ProcessingState.FAILED
        assert result.failed == 1
        assert calls == []


class TestOutageCatchUp:
    @override_settings(GITHUB_WEBHOOK_SECRET=WEBHOOK_SECRET)
    def test_backlog_catches_up_in_delivery_order_with_limit(self, monkeypatch):
        """A9/GIT-005: after an outage the backlog drains FIFO under the limit."""
        calls = []
        install_fake_contributions(monkeypatch, calls)
        RepositoryConnectionFactory(repository_node_id="R_kgDOKExAmPlE")
        first = ingest_pending("delivery-0001", pr_id=1001)
        second = ingest_pending("delivery-0002", pr_id=1002)
        third = ingest_pending("delivery-0003", pr_id=1003)

        partial = process_pending(limit=2)
        assert partial.processed == 2
        assert ProviderEvent.objects.filter(processing_state=ProcessingState.PENDING).count() == 1

        rest = process_pending(limit=10)
        assert rest.processed == 1
        first.refresh_from_db()
        second.refresh_from_db()
        third.refresh_from_db()
        assert first.processed_at <= second.processed_at <= third.processed_at
        credited_event_ids = [parsed.event_id for parsed, _project in calls]
        assert credited_event_ids == ["1001", "1002", "1003"]

    @override_settings(GITHUB_WEBHOOK_SECRET=WEBHOOK_SECRET)
    def test_duplicate_delivery_during_backlog_credits_once(self, monkeypatch):
        """GIT-005: a redelivered webhook during catch-up yields exactly one contribution."""
        calls = []
        install_fake_contributions(monkeypatch, calls)
        RepositoryConnectionFactory(repository_node_id="R_kgDOKExAmPlE")
        first = ingest_pending("delivery-0001")
        again = ingest_pending("delivery-0001")

        assert again.pk == first.pk
        assert ProviderEvent.objects.count() == 1

        process_pending(limit=10)
        assert len(calls) == 1
        first.refresh_from_db()
        assert first.processing_state == ProcessingState.PROCESSED
