from io import StringIO
from typing import ClassVar

import pytest
from django.core.management import CommandError, call_command
from django.test import override_settings

from apps.github_sync.enums import SyncState
from apps.github_sync.services import ReconciliationPage
from apps.github_sync.tests.factories import RepositoryConnectionFactory

pytestmark = [pytest.mark.unit, pytest.mark.github_webhook, pytest.mark.django_db]

FETCHER_PATH = "apps.github_sync.tests.test_reconcile_repositories_command.RecordingFetcher"


class RecordingFetcher:
    """GIT-006: importable stub fetcher wired through GITHUB_RECONCILE_FETCHER."""

    calls: ClassVar[list[tuple[int, str, object]]] = []
    fail_node_ids: ClassVar[frozenset[str]] = frozenset()

    def __init__(self):
        self.page = ReconciliationPage(events=(), next_cursor="cursor-next")

    def fetch(self, repository_connection, cursor, since):
        RecordingFetcher.calls.append((repository_connection.pk, cursor, since))
        if repository_connection.repository_node_id in RecordingFetcher.fail_node_ids:
            raise RuntimeError("provider unavailable")
        return self.page


@pytest.fixture(autouse=True)
def reset_recording_fetcher():
    RecordingFetcher.calls = []
    RecordingFetcher.fail_node_ids = frozenset()


class TestReconcileRepositoriesCommand:
    @override_settings(GITHUB_RECONCILE_FETCHER=FETCHER_PATH)
    def test_fetcher_is_invoked_per_active_connection(self):
        """GIT-006: every non-stopped connection is reconciled through the configured fetcher."""
        first = RepositoryConnectionFactory()
        second = RepositoryConnectionFactory()
        out = StringIO()

        call_command("reconcile_repositories", stdout=out)

        assert sorted(pk for pk, _cursor, _since in RecordingFetcher.calls) == [
            first.pk,
            second.pk,
        ]
        first.refresh_from_db()
        second.refresh_from_db()
        assert first.last_synced_at is not None
        assert second.last_synced_at is not None
        assert first.sync_state == SyncState.IDLE
        assert "recovered=0" in out.getvalue()

    @override_settings(GITHUB_RECONCILE_FETCHER=FETCHER_PATH)
    def test_stopped_connections_are_skipped(self):
        """GIT-006/GIT-011: reconciliation never fetches a STOPPED connection."""
        stopped = RepositoryConnectionFactory(sync_state=SyncState.STOPPED)
        active = RepositoryConnectionFactory()

        call_command("reconcile_repositories", stdout=StringIO())

        assert [pk for pk, _cursor, _since in RecordingFetcher.calls] == [active.pk]
        stopped.refresh_from_db()
        assert stopped.last_synced_at is None

    @override_settings(GITHUB_RECONCILE_FETCHER=FETCHER_PATH)
    def test_one_failing_repository_does_not_abort_the_rest(self):
        """GIT-006: a failing repository degrades alone; siblings still reconcile."""
        failing = RepositoryConnectionFactory()
        healthy = RepositoryConnectionFactory()
        RecordingFetcher.fail_node_ids = frozenset({failing.repository_node_id})
        out = StringIO()

        with pytest.raises(CommandError):
            call_command("reconcile_repositories", stdout=out)

        failing.refresh_from_db()
        healthy.refresh_from_db()
        assert failing.sync_state == SyncState.DEGRADED
        assert failing.last_synced_at is None
        assert healthy.sync_state == SyncState.IDLE
        assert healthy.last_synced_at is not None
        assert healthy.full_name in out.getvalue()

    def test_unconfigured_fetcher_is_a_clear_noop(self):
        """GIT-006: without GITHUB_RECONCILE_FETCHER the sweep is a documented no-op."""
        connection = RepositoryConnectionFactory()
        out = StringIO()

        call_command("reconcile_repositories", stdout=out)

        assert "GITHUB_RECONCILE_FETCHER" in out.getvalue()
        connection.refresh_from_db()
        assert connection.sync_state == SyncState.IDLE
        assert connection.last_synced_at is None

    @override_settings(GITHUB_RECONCILE_FETCHER="apps.github_sync.tests.nothing.Here")
    def test_invalid_fetcher_path_fails_loudly(self):
        """GIT-006: an unimportable fetcher path is an explicit configuration error."""

        with pytest.raises(CommandError):
            call_command("reconcile_repositories", stdout=StringIO())
