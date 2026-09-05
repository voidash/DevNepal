from dataclasses import dataclass
from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.github_sync.enums import DeliverySource, ProcessingState, SyncState
from apps.github_sync.errors import ReconciliationError
from apps.github_sync.models import ProviderEvent
from apps.github_sync.services import ReconciliationEvent, ReconciliationPage, reconcile
from apps.github_sync.tests.factories import (
    ProviderEventFactory,
    RepositoryConnectionFactory,
    parsed_payload,
)
from apps.github_sync.webhooks import ParsedEvent

pytestmark = [pytest.mark.unit, pytest.mark.github_webhook, pytest.mark.django_db]


@dataclass
class StubFetcher:
    page: ReconciliationPage | None = None
    error: Exception | None = None
    calls: list[tuple[object, str, object]] | None = None

    def fetch(self, repository_connection, cursor, since):
        if self.calls is not None:
            self.calls.append((repository_connection, cursor, since))
        if self.error is not None:
            raise self.error
        assert self.page is not None
        return self.page


def fetched_event(connection, event_id=987654, delivery_id="reconciliation-987654"):
    payload = parsed_payload(node_id=connection.repository_node_id, event_id=event_id)
    return ReconciliationEvent(
        event_type="pull_request",
        delivery_id=delivery_id,
        parsed_event=ParsedEvent(**payload),
    )


class TestReconcile:
    def test_persists_fetched_verified_events_and_advances_cursor(self):
        """GIT-006/GIT-012: a successful sweep durably queues verified missed events."""
        connection = RepositoryConnectionFactory()
        event = fetched_event(connection)
        fetcher = StubFetcher(page=ReconciliationPage(events=(event,), next_cursor="cursor-2"))

        recovered = reconcile(connection, since="2026-09-01T00:00:00Z", fetcher=fetcher)

        assert recovered == 1
        row = ProviderEvent.objects.get(provider_event_id="987654")
        assert row.repository == connection
        assert row.source == DeliverySource.RECONCILIATION
        assert row.signature_valid is True
        assert row.processing_state == ProcessingState.PENDING
        assert row.payload == parsed_payload(node_id=connection.repository_node_id, event_id=987654)
        connection.refresh_from_db()
        assert connection.sync_cursor == "cursor-2"
        assert connection.sync_state == SyncState.IDLE
        assert connection.last_synced_at is not None

    def test_existing_provider_event_id_is_not_reinserted(self):
        """GIT-006/GIT-005: reconciliation skips events already recorded by webhook delivery."""
        connection = RepositoryConnectionFactory()
        ProviderEventFactory(
            repository=connection,
            node_id=connection.repository_node_id,
            event_id=987654,
        )
        fetcher = StubFetcher(
            page=ReconciliationPage(
                events=(
                    fetched_event(connection, delivery_id="reconciliation-existing"),
                    fetched_event(connection, event_id=987655, delivery_id="reconciliation-new"),
                ),
                next_cursor="cursor-3",
            )
        )

        recovered = reconcile(connection, since=None, fetcher=fetcher)

        assert recovered == 1
        assert ProviderEvent.objects.filter(provider_event_id="987654").count() == 1
        assert ProviderEvent.objects.filter(provider_event_id="987655").count() == 1
        connection.refresh_from_db()
        assert connection.sync_cursor == "cursor-3"

    def test_fetch_failure_is_logged_and_leaves_cursor_recoverable(self, caplog):
        """GIT-006: a provider failure degrades the connection without advancing its cursor."""
        connection = RepositoryConnectionFactory(sync_cursor="cursor-1")
        fetcher = StubFetcher(error=RuntimeError("rate limit unavailable"))

        with pytest.raises(ReconciliationError):
            reconcile(connection, since=None, fetcher=fetcher)

        connection.refresh_from_db()
        assert ProviderEvent.objects.count() == 0
        assert connection.sync_cursor == "cursor-1"
        assert connection.sync_state == SyncState.DEGRADED
        assert connection.health_note == "reconciliation failed"
        assert connection.sync_failure_count == 1
        assert connection.next_sync_attempt_at > timezone.now()
        assert "reconciliation fetch failed" in caplog.text

    @override_settings(GITHUB_SYNC_RETRY_BASE_SECONDS=30, GITHUB_SYNC_RETRY_MAX_SECONDS=300)
    def test_repeated_failure_persists_exponential_retry_schedule(self, monkeypatch):
        """GIT-006-U2: reconciliation failure persists bounded exponential backoff."""
        connection = RepositoryConnectionFactory(sync_failure_count=2)
        fetcher = StubFetcher(error=RuntimeError("rate limited"))
        now = timezone.now()
        monkeypatch.setattr("apps.github_sync.services.timezone.now", lambda: now)

        with pytest.raises(ReconciliationError):
            reconcile(connection, since=None, fetcher=fetcher)

        connection.refresh_from_db()
        assert connection.sync_failure_count == 3
        assert connection.next_sync_attempt_at == now + timedelta(seconds=120)

    def test_success_clears_persisted_failure_state(self):
        """GIT-006: a healed connection clears retry state after a successful fetch."""
        connection = RepositoryConnectionFactory(
            sync_failure_count=3,
            next_sync_attempt_at=timezone.now(),
            health_note="reconciliation failed",
        )
        fetcher = StubFetcher(page=ReconciliationPage(events=(), next_cursor="healed"))

        reconcile(connection, since=None, fetcher=fetcher)

        connection.refresh_from_db()
        assert connection.sync_failure_count == 0
        assert connection.next_sync_attempt_at is None
        assert connection.health_note == ""

    def test_stopped_connection_is_not_fetched(self):
        """GIT-006/GIT-011: reconciliation never resumes a stopped connection."""
        connection = RepositoryConnectionFactory(sync_state=SyncState.STOPPED)
        calls = []
        fetcher = StubFetcher(
            page=ReconciliationPage(events=(), next_cursor="cursor-2"), calls=calls
        )

        recovered = reconcile(connection, since=None, fetcher=fetcher)

        assert recovered == 0
        assert calls == []
