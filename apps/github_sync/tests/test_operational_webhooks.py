import json

import pytest
from django.test import override_settings

from apps.audit.models import AuditEvent
from apps.github_sync.enums import ProcessingState, SyncState
from apps.github_sync.services import enroll_repository, ingest_webhook, process_pending
from apps.github_sync.tests.factories import (
    WEBHOOK_SECRET,
    ProviderEventFactory,
    RepositoryConnectionFactory,
    sign_body,
)

pytestmark = [pytest.mark.unit, pytest.mark.github_webhook, pytest.mark.django_db]


def deliver(event, payload, delivery_id):
    body = json.dumps(payload).encode()
    return ingest_webhook("github", event, delivery_id, sign_body(body), None, body)


@override_settings(GITHUB_WEBHOOK_SECRET=WEBHOOK_SECRET)
def test_installation_suspend_stops_and_unsuspend_requires_explicit_reenrollment():
    """GIT-005/GIT-011: suspension is immediate; unsuspend cannot restore a binding."""
    connection = RepositoryConnectionFactory(installation_id=8123)
    project_id = connection.project_id

    suspended = deliver(
        "installation", {"action": "suspend", "installation": {"id": 8123}}, "suspend-1"
    )

    connection.refresh_from_db()
    assert suspended.processing_state == ProcessingState.PROCESSED
    assert connection.sync_state == SyncState.STOPPED
    assert connection.project_id is None
    assert connection.deactivated_at is not None
    assert connection.access_revoked_reason == "installation_suspended"
    assert AuditEvent.objects.filter(action="github_repository.installation_suspended").count() == 1

    # A distinct redelivery is still state-idempotent and creates no duplicate audit mutation.
    deliver("installation", {"action": "suspend", "installation": {"id": 8123}}, "suspend-2")
    assert AuditEvent.objects.filter(action="github_repository.installation_suspended").count() == 1

    deliver("installation", {"action": "unsuspend", "installation": {"id": 8123}}, "unsuspend-1")
    connection.refresh_from_db()
    assert connection.sync_state == SyncState.STOPPED
    assert connection.deactivated_at is not None
    assert connection.access_revoked_reason == "installation_unsuspended_unbound"
    assert "explicit re-enrollment" in connection.health_note
    # Provider access returning deliberately does not restore a stale project binding.
    assert connection.project_id is None
    assert project_id is not None


@override_settings(GITHUB_WEBHOOK_SECRET=WEBHOOK_SECRET)
def test_installation_deleted_cannot_be_revived_by_unsuspend():
    """GIT-011: uninstall is permanent until a fresh explicit enrollment."""
    connection = RepositoryConnectionFactory(installation_id=8124)
    deliver("installation", {"action": "deleted", "installation": {"id": 8124}}, "delete-1")
    deliver("installation", {"action": "unsuspend", "installation": {"id": 8124}}, "unsuspend-2")
    connection.refresh_from_db()
    assert connection.sync_state == SyncState.STOPPED
    assert connection.project_id is None
    assert connection.access_revoked_reason == "installation_deleted"


@override_settings(GITHUB_WEBHOOK_SECRET=WEBHOOK_SECRET)
def test_explicit_reenrollment_can_restore_a_removed_repository():
    """GIT-003/GIT-011: only a fresh provider-authorized enrollment restores access."""
    connection = RepositoryConnectionFactory(installation_id=8125, repository_id=7001)
    deliver("installation", {"action": "deleted", "installation": {"id": 8125}}, "delete-2")

    outcome = enroll_repository(
        connection.activated_by,
        installation_id=9125,
        repository_id=7001,
        node_id=connection.repository_node_id,
        full_name=connection.full_name,
        granted_scopes=["contents:read"],
        is_public=True,
    )

    outcome.connection.refresh_from_db()
    assert outcome.created is False
    assert outcome.connection.installation_id == 9125
    assert outcome.connection.sync_state == SyncState.IDLE
    assert outcome.connection.deactivated_at is None
    assert outcome.connection.access_revoked_reason == ""
    assert AuditEvent.objects.filter(action="github_repository.reenroll").count() == 1


@override_settings(GITHUB_WEBHOOK_SECRET=WEBHOOK_SECRET)
def test_removed_repository_only_revokes_matching_installation_repository():
    """GIT-003/GIT-011: repository removal cannot revoke a same-id foreign installation."""
    removed = RepositoryConnectionFactory(installation_id=9001, repository_id=501)
    sibling = RepositoryConnectionFactory(installation_id=9001, repository_id=502)
    foreign = RepositoryConnectionFactory(installation_id=9002, repository_id=503)

    deliver(
        "installation_repositories",
        {
            "action": "removed",
            "installation": {"id": 9001},
            "repositories_removed": [{"id": 501, "node_id": removed.repository_node_id}],
        },
        "repo-remove-1",
    )

    for connection in (removed, sibling, foreign):
        connection.refresh_from_db()
    assert removed.sync_state == SyncState.STOPPED
    assert removed.project_id is None
    assert removed.access_revoked_reason == "repository_removed"
    assert sibling.sync_state == SyncState.IDLE
    assert foreign.sync_state == SyncState.IDLE


@override_settings(GITHUB_WEBHOOK_SECRET=WEBHOOK_SECRET)
def test_stopped_repository_pending_event_never_creates_candidate():
    """GIT-011: already queued work cannot cross a provider revocation boundary."""
    connection = RepositoryConnectionFactory(
        sync_state=SyncState.STOPPED, access_revoked_reason="repository_removed"
    )
    event = ProviderEventFactory(repository=connection, node_id=connection.repository_node_id)

    result = process_pending(limit=10)

    event.refresh_from_db()
    assert result.failed == 1
    assert event.processing_state == ProcessingState.FAILED
    assert "stopped" in event.last_error
