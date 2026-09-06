import hashlib
import json
from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.github_sync.enums import ProcessingState
from apps.github_sync.errors import WebhookReplayError, WebhookSignatureError
from apps.github_sync.models import ProviderEvent
from apps.github_sync.services import ingest_webhook
from apps.github_sync.tests.factories import (
    WEBHOOK_SECRET,
    GithubConnectionFactory,
    RepositoryConnectionFactory,
    pr_merged_body,
    sign_body,
)

pytestmark = [pytest.mark.unit, pytest.mark.github_webhook, pytest.mark.django_db]

DELIVERY_ID = "72d3162e-cc78-11e3-81ab-4c9367dc0958"
UNSET = object()


def fresh_timestamp() -> str:
    return timezone.now().isoformat()


def ingest(
    body=None, delivery_id=DELIVERY_ID, event="pull_request", signature=UNSET, timestamp=None
):
    body = pr_merged_body() if body is None else body
    if signature is UNSET:
        signature = sign_body(body)
    return ingest_webhook(
        "github",
        event,
        delivery_id,
        signature,
        timestamp if timestamp is not None else fresh_timestamp(),
        body,
    )


class TestSignatureValidation:
    @override_settings(GITHUB_WEBHOOK_SECRET=WEBHOOK_SECRET)
    def test_invalid_signature_records_rejected_row_then_raises(self):
        """GIT-004: a delivery with a bad signature is stored REJECTED, then rejected to caller."""
        body = pr_merged_body()
        forged = "sha256=" + "0" * 64
        with pytest.raises(WebhookSignatureError):
            ingest(body=body, signature=forged)
        row = ProviderEvent.objects.get(delivery_id=DELIVERY_ID)
        assert row.processing_state == ProcessingState.REJECTED
        assert row.signature_valid is False
        assert row.signature_note == "invalid"
        assert row.processed_at is not None
        assert row.correlation_id != ""
        assert "signature" in row.last_error

    @override_settings(GITHUB_WEBHOOK_SECRET=WEBHOOK_SECRET)
    def test_missing_signature_header_is_rejected_with_note(self):
        """GIT-004: deliveries without a signature header never reach processing."""
        with pytest.raises(WebhookSignatureError):
            ingest(signature=None)
        row = ProviderEvent.objects.get(delivery_id=DELIVERY_ID)
        assert row.processing_state == ProcessingState.REJECTED
        assert row.signature_note == "missing"

    @override_settings(GITHUB_WEBHOOK_SECRET=WEBHOOK_SECRET)
    def test_redelivered_rejected_delivery_creates_no_second_row(self):
        """GIT-004/GIT-005: a rejected redelivery collapses onto the existing row."""
        with pytest.raises(WebhookSignatureError):
            ingest(signature=None)
        row = ingest(signature=None)
        assert row.processing_state == ProcessingState.REJECTED
        assert ProviderEvent.objects.count() == 1


class TestReplayWindow:
    @override_settings(GITHUB_WEBHOOK_SECRET=WEBHOOK_SECRET)
    def test_stale_timestamp_records_rejected_row_then_raises(self):
        """GIT-005: valid signature but stale timestamp is a replay and is rejected."""
        stale = (timezone.now() - timedelta(hours=1)).isoformat()
        with pytest.raises(WebhookReplayError):
            ingest(timestamp=stale)
        row = ProviderEvent.objects.get(delivery_id=DELIVERY_ID)
        assert row.processing_state == ProcessingState.REJECTED
        assert row.signature_valid is True
        assert row.signature_note == "valid"
        assert "replay" in row.last_error


class TestUnsupportedEvents:
    @override_settings(
        GITHUB_WEBHOOK_SECRET=WEBHOOK_SECRET,
        GITHUB_VERIFIED_EVENT_TYPES=("issues", "release"),
    )
    def test_configured_event_allowlist_is_enforced_before_queueing(self):
        """GIT-007: disabled verified kinds never enter the pending ledger queue."""
        RepositoryConnectionFactory(repository_node_id="R_kgDOKExAmPlE")
        row = ingest()
        assert row.processing_state == ProcessingState.PROCESSED
        assert "not configured" in row.last_error

    @override_settings(GITHUB_WEBHOOK_SECRET=WEBHOOK_SECRET)
    def test_pr_for_non_default_branch_is_not_queued(self):
        """GIT-007: only PR activity targeting the project's configured branch is eligible."""
        connection = RepositoryConnectionFactory(repository_node_id="R_kgDOKExAmPlE")
        connection.project.default_branch = "release"
        connection.project.save(update_fields=["default_branch"])
        row = ingest()
        assert row.processing_state == ProcessingState.PROCESSED
        assert "default branch" in row.last_error

    @override_settings(GITHUB_WEBHOOK_SECRET=WEBHOOK_SECRET)
    def test_unsupported_event_type_is_processed_as_ignored(self):
        """GIT-007: events outside the verified set are recorded PROCESSED, never PENDING."""
        body = json.dumps(
            {
                "action": "created",
                "repository": {"id": 555001, "node_id": "R_kgDOKExAmPlE", "name": "gov-portal"},
                "sender": {"login": "cdjk", "type": "User"},
            }
        ).encode()
        row = ingest(event="star", body=body)
        assert row.processing_state == ProcessingState.PROCESSED
        assert row.processed_at is not None
        assert "unsupported" in row.last_error
        assert row.payload is None

    @override_settings(GITHUB_WEBHOOK_SECRET=WEBHOOK_SECRET)
    def test_push_event_is_ignored_without_credit(self):
        """D7/GIT-008: raw push events are recorded ignored, never queued for credit."""
        body = json.dumps(
            {
                "repository": {"id": 555001, "node_id": "R_kgDOKExAmPlE", "name": "gov-portal"},
                "sender": {"login": "cdjk", "type": "User"},
            }
        ).encode()
        row = ingest(event="push", body=body)
        assert row.processing_state == ProcessingState.PROCESSED
        assert "unsupported" in row.last_error


class TestValidDelivery:
    @override_settings(GITHUB_WEBHOOK_SECRET=WEBHOOK_SECRET)
    def test_merged_pr_records_pending_event_with_full_provenance(self):
        """GIT-012: a valid merged-PR delivery retains every provenance field."""
        connection = RepositoryConnectionFactory(repository_node_id="R_kgDOKExAmPlE")
        account = GithubConnectionFactory(login="cdjk")
        body = pr_merged_body()
        row = ingest(body=body)
        assert row.processing_state == ProcessingState.PENDING
        assert row.processed_at is None
        assert row.provider == "github"
        assert row.event_type == "pull_request"
        assert row.delivery_id == DELIVERY_ID
        assert row.provider_event_id == "987654"
        assert row.signature_valid is True
        assert row.signature_note == "valid"
        assert row.payload_digest == hashlib.sha256(body).hexdigest()
        assert row.repository == connection
        assert row.actor == account.user
        assert row.received_at is not None

    @override_settings(GITHUB_WEBHOOK_SECRET=WEBHOOK_SECRET)
    def test_payload_stores_parsed_fields_only(self):
        """GIT-010/GIT-012: minimal parsed payload; raw sender/body content never stored."""
        row = ingest()
        assert set(row.payload) == {
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
            "public_snapshot_lifecycle",
        }
        assert row.payload["kind"] == "pr_merged"
        assert row.payload["event_id"] == "987654"
        assert row.payload["actor_login"] == "cdjk"
        assert set(row.payload["public_snapshot_lifecycle"]) == {
            "action",
            "repository_node_id",
            "snapshot_item",
        }
        assert "sender" not in row.payload
        assert "pull_request" not in row.payload

    @override_settings(GITHUB_WEBHOOK_SECRET=WEBHOOK_SECRET)
    def test_unmapped_repository_still_queues_pending(self):
        """GIT-012/A9: mapping happens at processing; ingest only links when resolvable."""
        row = ingest()
        assert row.repository is None
        assert row.processing_state == ProcessingState.PENDING


class TestDeduplication:
    @override_settings(GITHUB_WEBHOOK_SECRET=WEBHOOK_SECRET)
    def test_same_delivery_id_collapses_onto_existing_row(self):
        """GIT-005/A5: a redelivered delivery returns the existing row, no second event."""
        first = ingest()
        second = ingest()
        assert second.pk == first.pk
        assert ProviderEvent.objects.count() == 1
        first.refresh_from_db()
        assert first.processing_state == ProcessingState.PENDING

    @override_settings(GITHUB_WEBHOOK_SECRET=WEBHOOK_SECRET)
    def test_same_event_under_new_delivery_is_duplicate_evidence(self):
        """GIT-005/D6: the event key catches re-delivery under a new GUID; evidence recorded."""
        first = ingest()
        second = ingest(delivery_id="0f0a2b40-new-delivery-guid")
        assert second.pk != first.pk
        assert second.processing_state == ProcessingState.DUPLICATE
        assert "987654" in second.last_error
        assert ProviderEvent.objects.count() == 2
        first.refresh_from_db()
        assert first.processing_state == ProcessingState.PENDING

    @override_settings(GITHUB_WEBHOOK_SECRET=WEBHOOK_SECRET)
    def test_duplicate_rows_are_never_queued_for_processing(self):
        """GIT-005/GIT-008: duplicate-evidence rows create no side effects downstream."""
        ingest()
        duplicate = ingest(delivery_id="0f0a2b40-new-delivery-guid")
        assert duplicate.processing_state == ProcessingState.DUPLICATE
        assert not ProviderEvent.objects.filter(
            processing_state=ProcessingState.PENDING,
            delivery_id="0f0a2b40-new-delivery-guid",
        ).exists()
