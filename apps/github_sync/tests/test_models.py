import uuid

import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.github_sync.enums import ProcessingState, Provider, SyncState
from apps.github_sync.tests.factories import (
    GithubConnectionFactory,
    ProviderEventFactory,
    RepositoryConnectionFactory,
)

pytestmark = [pytest.mark.unit, pytest.mark.github_webhook, pytest.mark.django_db]


class TestGithubConnection:
    def test_str_and_active_default(self):
        """GIT-011: a fresh connection is active until revoked_at is set."""
        connection = GithubConnectionFactory()
        assert str(connection) == f"{connection.user.username} GitHub:{connection.login}"
        assert connection.revoked_at is None
        assert connection.is_active is True

    def test_revoked_connection_is_inactive(self):
        """GIT-011: revoked_at flips the connection to the disconnected state."""
        connection = GithubConnectionFactory(revoked_at="2026-09-03T00:00:00Z")
        assert connection.is_active is False

    def test_login_is_nfc_normalized(self):
        """DSC-003: provider login text is NFC-normalized on save."""
        nfd_login = "gov-member" + "e" + "\u0301"
        connection = GithubConnectionFactory(login=nfd_login)
        connection.refresh_from_db()
        assert connection.login == "gov-member\u00e9"


class TestRepositoryConnection:
    def test_str_and_defaults(self):
        """GIT-003: repository connections default to IDLE sync with empty cursor."""
        connection = RepositoryConnectionFactory()
        assert str(connection) == connection.full_name
        assert connection.provider == Provider.GITHUB
        assert connection.sync_state == SyncState.IDLE
        assert connection.sync_cursor == ""
        assert connection.deactivated_at is None

    def test_repository_unique_per_provider(self):
        """GIT-003: one connection row per (provider, repository_id)."""
        first = RepositoryConnectionFactory()
        with pytest.raises(IntegrityError):
            RepositoryConnectionFactory(
                provider=first.provider,
                repository_id=first.repository_id,
            )

    def test_full_name_is_nfc_normalized(self):
        """DSC-003: repository full names are NFC-normalized on save."""
        nfd_name = "moit/serva" + "e" + "\u0301"
        connection = RepositoryConnectionFactory(full_name=nfd_name)
        connection.refresh_from_db()
        assert connection.full_name == "moit/serva\u00e9"


class TestProviderEvent:
    def test_uuid_pk_and_defaults(self):
        """GIT-012: ledger rows use UUID pks and default to PENDING processing."""
        event = ProviderEventFactory()
        assert isinstance(event.pk, uuid.UUID)
        assert event.processing_state == ProcessingState.PENDING
        assert event.processing_attempts == 0
        assert event.received_at is not None
        assert event.processed_at is None
        assert event.signature_valid is True

    def test_str_shows_provider_type_and_event_id(self):
        """GIT-012: __str__ retains provider, event type and provider event id."""
        event = ProviderEventFactory()
        assert str(event) == f"github:pull_request {event.provider_event_id}"

    def test_delivery_key_is_unique(self):
        """GIT-005/D6: (provider, delivery_id) is unique — structural idempotency."""
        first = ProviderEventFactory()
        with pytest.raises(IntegrityError):
            ProviderEventFactory(provider=first.provider, delivery_id=first.delivery_id)

    def test_event_key_is_unique(self):
        """GIT-005/D6: (provider, provider_event_id) is the second dedup key."""
        first = ProviderEventFactory()
        with pytest.raises(IntegrityError):
            ProviderEventFactory(
                provider=first.provider,
                provider_event_id=first.provider_event_id,
            )

    def test_processing_state_covers_pipeline_values(self):
        """GIT-005: the pipeline states PENDING/PROCESSED/DUPLICATE/FAILED/REJECTED exist."""
        values = set(ProcessingState.values)
        assert {"pending", "processed", "duplicate", "failed", "rejected"} <= values

    def test_payload_stores_only_parsed_fields(self):
        """GIT-010/GIT-012: payload carries parsed fields only, never raw bodies."""
        event = ProviderEventFactory()
        assert set(event.payload) == {
            "kind",
            "action",
            "actor_login",
            "actor_type",
            "is_bot",
            "repository_node_id",
            "repository_name",
            "number",
            "event_id",
            "triggered_by_login",
        }

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("id", uuid.uuid4()),
            ("provider", "other"),
            ("event_type", "issue"),
            ("delivery_id", "replacement-delivery"),
            ("provider_event_id", "replacement-event"),
            ("source", "reconciliation"),
            ("signature_valid", False),
            ("signature_note", "invalid"),
            ("received_at", timezone.now()),
            ("payload", {"tampered": True}),
            ("payload_digest", "0" * 64),
            ("correlation_id", "replacement-correlation"),
        ],
    )
    def test_provenance_fields_are_write_once(self, field, value):
        """GIT-012/SEC-008: imported event identity, payload, and provenance cannot change."""
        event = ProviderEventFactory()
        setattr(event, field, value)

        with pytest.raises(PermissionError):
            event.save()

    def test_processing_fields_remain_mutable(self):
        """GIT-012: processing may resolve repository, actor, state, errors, and completion data."""
        event = ProviderEventFactory()
        event.repository = RepositoryConnectionFactory()
        event.actor = GithubConnectionFactory().user
        event.processing_state = ProcessingState.PROCESSED
        event.processing_attempts = 1
        event.last_error = "transient failure recovered"
        event.processed_at = timezone.now()

        event.save(
            update_fields=[
                "repository",
                "actor",
                "processing_state",
                "processing_attempts",
                "last_error",
                "processed_at",
            ]
        )
        event.refresh_from_db()

        assert event.processing_state == ProcessingState.PROCESSED
        assert event.processing_attempts == 1
        assert event.last_error == "transient failure recovered"
        assert event.processed_at is not None

    def test_queryset_rejects_provenance_updates(self):
        """GIT-012/SEC-008: bulk writes cannot alter imported event provenance."""
        event = ProviderEventFactory()

        with pytest.raises(PermissionError):
            type(event).objects.filter(pk=event.pk).update(payload={"tampered": True})

    def test_queryset_allows_processing_updates(self):
        """GIT-012: workers may efficiently update processing state and attempts."""
        event = ProviderEventFactory()

        updated = (
            type(event)
            .objects.filter(pk=event.pk)
            .update(
                processing_state=ProcessingState.FAILED,
                processing_attempts=1,
                last_error="transient failure",
            )
        )
        event.refresh_from_db()

        assert updated == 1
        assert event.processing_state == ProcessingState.FAILED
        assert event.processing_attempts == 1
