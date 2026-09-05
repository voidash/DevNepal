import json

import pytest
from django.test import override_settings

from apps.audit.models import AuditEvent
from apps.github_sync.enums import SyncState
from apps.github_sync.errors import ConnectionNotFoundError
from apps.github_sync.models import GithubConnection, RepositoryConnection
from apps.github_sync.services import disconnect
from apps.github_sync.tests.factories import (
    GithubConnectionFactory,
    RepositoryConnectionFactory,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

TOKEN_SENTINEL = "ghp_tokensemaphore0123456789"


def purge_hook(calls):
    def _purge(user):
        calls.append(user)
        return 1

    return _purge


class TestDisconnect:
    def test_disconnect_revokes_stops_sync_and_purges_tokens(self):
        """GIT-011: disconnect revokes the connection, stops repository sync, deletes tokens."""
        user = GithubConnectionFactory().user
        stopped = RepositoryConnectionFactory.create_batch(2, activated_by=user)
        untouched = RepositoryConnectionFactory()
        purges = []

        with override_settings(GITHUB_TOKEN_PURGE=purge_hook(purges)):
            disconnect(user)

        connection = GithubConnection.objects.get(user=user)
        assert connection.revoked_at is not None
        assert connection.is_active is False
        for connection_repo in stopped:
            connection_repo.refresh_from_db()
            assert connection_repo.sync_state == SyncState.STOPPED
            assert connection_repo.deactivated_at is not None
        untouched.refresh_from_db()
        assert untouched.sync_state == SyncState.IDLE
        assert purges == [user]

    def test_disconnect_records_audit_without_token_material(self):
        """AUTH-008/GIT-011: revocation is audited and token values never reach the audit row."""
        connection = GithubConnectionFactory()
        user = connection.user
        purges = []

        with override_settings(GITHUB_TOKEN_PURGE=purge_hook(purges)):
            disconnect(user)

        audit = AuditEvent.objects.get(action="github_connection.disconnect")
        assert audit.actor == user
        assert audit.object_id == str(connection.pk)
        payload = json.dumps([audit.before, audit.after])
        assert TOKEN_SENTINEL not in payload
        assert "ghp_" not in payload
        assert purges == [user]

    def test_disconnect_without_connection_raises(self):
        """GIT-011: disconnecting a user with no connection is an explicit error."""
        from apps.ministries.tests.factories import UserFactory

        with pytest.raises(ConnectionNotFoundError):
            disconnect(UserFactory())

    def test_disconnect_is_idempotent(self):
        """GIT-011: a second disconnect neither re-audits nor fails."""
        connection = GithubConnectionFactory()
        purges = []
        with override_settings(GITHUB_TOKEN_PURGE=purge_hook(purges)):
            disconnect(connection.user)
            disconnect(connection.user)
        assert AuditEvent.objects.filter(action="github_connection.disconnect").count() == 1
        assert purges == [connection.user]

    def test_disconnect_without_secret_store_still_revokes(self):
        """GIT-011: revocation proceeds even when no token store is configured."""
        connection = GithubConnectionFactory()
        RepositoryConnectionFactory(activated_by=connection.user)

        disconnect(connection.user)

        connection.refresh_from_db()
        assert connection.is_active is False
        assert (
            RepositoryConnection.objects.get(activated_by=connection.user).sync_state
            == SyncState.STOPPED
        )
