import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.github_sync.enums import SyncState
from apps.github_sync.models import GithubConnection, RepositoryConnection
from apps.github_sync.tests.factories import (
    GithubConnectionFactory,
    RepositoryConnectionFactory,
)
from apps.ministries.tests.factories import UserFactory

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


@pytest.fixture(autouse=True)
def github_sync_urlconf():
    with override_settings(ROOT_URLCONF="apps.github_sync.tests.urls"):
        yield


class TestConnectionStatusView:
    def test_requires_login(self, client):
        """GIT-011/AUTH-008: the connection status page is member-only."""
        response = client.get(reverse("github_sync:connection"))

        assert response.status_code == 302
        assert reverse("accounts:login") in response.url

    def test_member_without_connection_is_redirected_to_the_dashboard(self, client):
        """AUTH-008: a member with no provider connection is routed to the connect action."""
        client.force_login(UserFactory())

        response = client.get(reverse("github_sync:connection"))

        assert response.status_code == 302
        assert response.url == reverse("accounts:dashboard")

    def test_status_shows_consent_scopes_and_sync_provenance(self, client):
        """AUTH-008: consent, scopes, timing and revocation state are visible; tokens never are."""
        synced_at = timezone.now()
        connection = GithubConnectionFactory(last_synced_at=synced_at)
        client.force_login(connection.user)

        response = client.get(reverse("github_sync:connection"))

        assert response.status_code == 200
        assert response.context["connection"] == connection
        content = response.content.decode()
        assert connection.login in content
        assert "read:user" in content
        assert "public_repo" in content
        assert "Connected" in content
        assert "ghp_" not in content

    def test_status_shows_disconnected_state_after_revocation(self, client):
        """GIT-011: a revoked connection renders the disconnected state, no disconnect action."""
        connection = GithubConnectionFactory(revoked_at=timezone.now())
        client.force_login(connection.user)

        response = client.get(reverse("github_sync:connection"))

        assert response.status_code == 200
        content = response.content.decode()
        assert "Disconnected" in content
        assert reverse("github_sync:disconnect") not in content


class TestDisconnectView:
    def test_get_is_not_allowed(self, client):
        """GIT-011: disconnect is a POST-only CSRF-protected state change."""
        client.force_login(GithubConnectionFactory().user)

        response = client.get(reverse("github_sync:disconnect"))

        assert response.status_code == 405

    def test_anonymous_post_redirects_to_login(self, client):
        """GIT-011/AUTH-008: disconnect is member-only."""

        response = client.post(reverse("github_sync:disconnect"))

        assert response.status_code == 302
        assert reverse("accounts:login") in response.url

    def test_post_disconnect_stops_sync_and_audits(self, client):
        """GIT-011/AUTH-008: POST disconnect revokes, stops sync, purges tokens, audits."""
        connection = GithubConnectionFactory()
        user = connection.user
        owned = RepositoryConnectionFactory(activated_by=user)
        foreign = RepositoryConnectionFactory()
        purges = []

        def purge(user_arg):
            purges.append(user_arg)
            return 1

        client.force_login(user)
        with override_settings(GITHUB_TOKEN_PURGE=purge):
            response = client.post(reverse("github_sync:disconnect"))

        assert response.status_code == 302
        assert response.url == reverse("github_sync:connection")
        connection.refresh_from_db()
        owned.refresh_from_db()
        foreign.refresh_from_db()
        assert connection.revoked_at is not None
        assert owned.sync_state == SyncState.STOPPED
        assert foreign.sync_state == SyncState.IDLE
        assert purges == [user]
        event = AuditEvent.objects.get(action="github_connection.disconnect")
        assert event.actor == user

    def test_post_disconnect_without_connection_is_404(self, client):
        """GIT-011: disconnecting with no provider connection is a 404, not a server error."""
        client.force_login(UserFactory())

        response = client.post(reverse("github_sync:disconnect"))

        assert response.status_code == 404
        assert not AuditEvent.objects.filter(action="github_connection.disconnect").exists()
        assert not GithubConnection.objects.exists()

    def test_post_disconnect_is_idempotent_for_revoked_connection(self, client):
        """GIT-011: repeating disconnect after revocation neither fails nor re-audits."""
        connection = GithubConnectionFactory(revoked_at=timezone.now())
        client.force_login(connection.user)

        response = client.post(reverse("github_sync:disconnect"))

        assert response.status_code == 302
        assert AuditEvent.objects.filter(action="github_connection.disconnect").count() == 0
        assert RepositoryConnection.objects.count() == 0
