import logging

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.github_sync.enums import SyncState
from apps.github_sync.models import RepositoryConnection
from apps.github_sync.tests.data import TEST_APP_KEY_PEM
from apps.github_sync.tests.factories import GithubConnectionFactory, RepositoryConnectionFactory
from apps.ministries.tests.factories import UserFactory

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

APP_ID = "987654"
INSTALLATION_ID = 42001
OTHER_INSTALLATION_ID = 42002
TOKEN_MAIN = "ghs_inmemory_token_main_0001"
TOKEN_OTHER = "ghs_inmemory_token_other_0002"
MEMBER_REPO_ID = 555001
MEMBER_REPO_2_ID = 555002
FOREIGN_REPO_ID = 555003


@pytest.fixture(autouse=True)
def github_sync_urlconf(settings):
    settings.ROOT_URLCONF = "apps.github_sync.tests.urls"


@pytest.fixture(autouse=True)
def clean_app_config(monkeypatch, settings):
    monkeypatch.delenv("GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY", raising=False)
    monkeypatch.delattr(settings, "GITHUB_APP_ID", raising=False)
    monkeypatch.delattr(settings, "GITHUB_APP_PRIVATE_KEY", raising=False)
    monkeypatch.delattr(settings, "GITHUB_APP_TRANSPORT", raising=False)


def configure_app(settings, transport):
    settings.GITHUB_APP_ID = APP_ID
    settings.GITHUB_APP_PRIVATE_KEY = TEST_APP_KEY_PEM
    settings.GITHUB_APP_TRANSPORT = transport


def github_api_transport():
    def handler(request):
        method = request["method"]
        url = request["url"]
        if method == "POST" and url.endswith(f"/app/installations/{INSTALLATION_ID}/access_tokens"):
            return 201, {"token": TOKEN_MAIN, "expires_at": "2026-09-05T00:00:00Z"}
        if method == "POST" and url.endswith(
            f"/app/installations/{OTHER_INSTALLATION_ID}/access_tokens"
        ):
            return 201, {"token": TOKEN_OTHER, "expires_at": "2026-09-05T00:00:00Z"}
        if method == "GET" and url.startswith("https://api.github.com/app/installations?"):
            return 200, [
                {
                    "id": INSTALLATION_ID,
                    "account": {"login": "cdjk"},
                    "permissions": {"contents": "read", "metadata": "read"},
                },
                {
                    "id": OTHER_INSTALLATION_ID,
                    "account": {"login": "other-org"},
                    "permissions": {"contents": "read", "metadata": "read"},
                },
            ]
        if method == "GET" and url.startswith("https://api.github.com/installation/repositories?"):
            if "page=1" not in url:
                return 200, {"total_count": 0, "repositories": []}
            if request["headers"]["Authorization"] == f"token {TOKEN_MAIN}":
                return 200, {
                    "total_count": 2,
                    "repositories": [
                        {
                            "id": MEMBER_REPO_ID,
                            "node_id": "R_kgDOMain00001",
                            "name": "gov-portal",
                            "full_name": "cdjk/gov-portal",
                            "private": False,
                            "owner": {"login": "cdjk"},
                        },
                        {
                            "id": MEMBER_REPO_2_ID,
                            "node_id": "R_kgDOMain00002",
                            "name": "simsara",
                            "full_name": "cdjk/simsara",
                            "private": True,
                            "owner": {"login": "cdjk"},
                        },
                    ],
                }
            return 200, {
                "total_count": 1,
                "repositories": [
                    {
                        "id": FOREIGN_REPO_ID,
                        "node_id": "R_kgDOOther0003",
                        "name": "secret-repo",
                        "full_name": "other-org/secret-repo",
                        "private": True,
                        "owner": {"login": "other-org"},
                    }
                ],
            }
        raise AssertionError(f"unexpected request {method} {url}")

    return handler


class TestConnectRepositoryAccess:
    def test_requires_login(self, client):
        """GIT-003: repository enrollment is a member-only route."""
        response = client.get(reverse("github_sync:connect_repository"))

        assert response.status_code == 302
        assert reverse("accounts:login") in response.url

    def test_unconfigured_github_app_is_404(self, client, settings):
        """GIT-001: without a configured GitHub App the enrollment route is disabled."""
        configure_app(settings, github_api_transport())
        settings.GITHUB_APP_ID = ""
        connection = GithubConnectionFactory(login="cdjk")
        client.force_login(connection.user)

        response = client.get(reverse("github_sync:connect_repository"))

        assert response.status_code == 404

    def test_member_without_github_connection_is_404(self, client, settings):
        """AUTH-008: a member who never linked GitHub has nothing to enroll from."""
        configure_app(settings, github_api_transport())
        client.force_login(UserFactory())

        response = client.get(reverse("github_sync:connect_repository"))

        assert response.status_code == 404

    def test_revoked_connection_is_404(self, client, settings):
        """GIT-011: a revoked connection no longer exposes repository enrollment."""
        configure_app(settings, github_api_transport())
        connection = GithubConnectionFactory(login="cdjk", revoked_at=timezone.now())
        client.force_login(connection.user)

        response = client.get(reverse("github_sync:connect_repository"))

        assert response.status_code == 404


class TestConnectRepositoryListing:
    def test_get_lists_only_member_owned_repositories(self, client, settings):
        """GIT-003: only repositories of the member's linked installation are selectable."""
        configure_app(settings, github_api_transport())
        connection = GithubConnectionFactory(login="cdjk")
        client.force_login(connection.user)

        response = client.get(reverse("github_sync:connect_repository"))

        assert response.status_code == 200
        content = response.content.decode()
        assert "cdjk/gov-portal" in content
        assert "cdjk/simsara" in content
        assert "other-org/secret-repo" not in content
        repos = response.context["repositories"]
        assert [repo.full_name for repo in repos] == ["cdjk/gov-portal", "cdjk/simsara"]

    def test_get_marks_already_enrolled_repositories(self, client, settings):
        """GIT-001: one active connection per repository; enrolled repos cannot re-enroll."""
        configure_app(settings, github_api_transport())
        connection = GithubConnectionFactory(login="cdjk")
        RepositoryConnectionFactory(
            installation_id=INSTALLATION_ID,
            repository_id=MEMBER_REPO_ID,
            repository_node_id="R_kgDOMain00001",
            full_name="cdjk/gov-portal",
            activated_by=connection.user,
        )
        client.force_login(connection.user)

        response = client.get(reverse("github_sync:connect_repository"))

        assert response.status_code == 200
        content = response.content.decode()
        assert "Enrolled" in content
        repos = response.context["repositories"]
        enrolled = {repo.full_name: repo.enrolled for repo in repos}
        assert enrolled == {"cdjk/gov-portal": True, "cdjk/simsara": False}

    def test_transport_error_renders_error_banner(self, client, settings, caplog):
        """GIT-001: provider outages degrade to a typed error and an on-page banner."""
        configure_app(settings, github_api_transport())

        def broken(request):
            raise OSError("connection refused")

        settings.GITHUB_APP_TRANSPORT = broken
        connection = GithubConnectionFactory(login="cdjk")
        client.force_login(connection.user)

        with caplog.at_level(logging.DEBUG):
            response = client.get(reverse("github_sync:connect_repository"))

        assert response.status_code == 200
        content = response.content.decode()
        assert "dn-state-banner" in content
        assert "GitHub could not be reached" in content
        assert response.context["repositories"] == []


class TestConnectRepositoryEnrollment:
    def test_post_enroll_creates_connection_and_audits(self, client, settings):
        """GIT-001/GIT-003: enrolling stores non-secret repository provenance and audits."""
        configure_app(settings, github_api_transport())
        connection = GithubConnectionFactory(login="cdjk")
        client.force_login(connection.user)

        response = client.post(
            reverse("github_sync:connect_repository"),
            {
                "installation_id": str(INSTALLATION_ID),
                "repository_id": str(MEMBER_REPO_ID),
                "full_name": "cdjk/forged-name",
            },
        )

        assert response.status_code == 302
        enrolled = RepositoryConnection.objects.get(repository_id=MEMBER_REPO_ID)
        assert enrolled.provider == "github"
        assert enrolled.installation_id == INSTALLATION_ID
        assert enrolled.repository_node_id == "R_kgDOMain00001"
        assert enrolled.full_name == "cdjk/gov-portal"
        assert enrolled.granted_scopes == ["contents:read", "metadata:read"]
        assert enrolled.is_public is True
        assert enrolled.project is None
        assert enrolled.activated_by == connection.user
        assert enrolled.sync_state == SyncState.IDLE
        event = AuditEvent.objects.get(action="github_repository.enroll")
        assert event.actor == connection.user
        assert event.object_id == str(enrolled.pk)
        assert event.after["full_name"] == "cdjk/gov-portal"
        assert event.after["repository_id"] == MEMBER_REPO_ID

    def test_post_duplicate_enroll_is_idempotent(self, client, settings):
        """GIT-001: re-enrolling an already connected repository changes nothing."""
        configure_app(settings, github_api_transport())
        connection = GithubConnectionFactory(login="cdjk")
        existing = RepositoryConnectionFactory(
            installation_id=INSTALLATION_ID,
            repository_id=MEMBER_REPO_ID,
            repository_node_id="R_kgDOMain00001",
            full_name="cdjk/gov-portal",
            activated_by=connection.user,
        )
        client.force_login(connection.user)

        response = client.post(
            reverse("github_sync:connect_repository"),
            {
                "installation_id": str(INSTALLATION_ID),
                "repository_id": str(MEMBER_REPO_ID),
            },
        )

        assert response.status_code == 302
        assert RepositoryConnection.objects.filter(repository_id=MEMBER_REPO_ID).count() == 1
        existing.refresh_from_db()
        assert existing.full_name == "cdjk/gov-portal"
        assert AuditEvent.objects.filter(action="github_repository.enroll").count() == 0

    def test_post_repository_outside_member_installations_is_404(self, client, settings):
        """AUTH-006: a member cannot enroll a repository outside their installations."""
        configure_app(settings, github_api_transport())
        connection = GithubConnectionFactory(login="cdjk")
        client.force_login(connection.user)

        response = client.post(
            reverse("github_sync:connect_repository"),
            {
                "installation_id": str(OTHER_INSTALLATION_ID),
                "repository_id": str(FOREIGN_REPO_ID),
            },
        )

        assert response.status_code == 404
        assert not RepositoryConnection.objects.filter(repository_id=FOREIGN_REPO_ID).exists()
        assert not AuditEvent.objects.filter(action="github_repository.enroll").exists()

    def test_enrolled_token_never_persisted_or_logged(self, client, settings, caplog):
        """AUTH-008/GIT-011: installation tokens stay in memory; nothing durable or logged."""
        configure_app(settings, github_api_transport())
        connection = GithubConnectionFactory(login="cdjk")
        client.force_login(connection.user)

        with caplog.at_level(logging.DEBUG):
            response = client.post(
                reverse("github_sync:connect_repository"),
                {
                    "installation_id": str(INSTALLATION_ID),
                    "repository_id": str(MEMBER_REPO_ID),
                },
            )

        assert response.status_code == 302
        persisted = "".join(
            str(value)
            for row in RepositoryConnection.objects.iterator()
            for value in vars(row).values()
        )
        persisted += str(list(AuditEvent.objects.values("before", "after")))
        persisted += response.content.decode()
        persisted += caplog.text
        assert TOKEN_MAIN not in persisted
        assert TOKEN_OTHER not in persisted
        assert "Bearer " not in persisted
        assert not any(field.name == "token" for field in RepositoryConnection._meta.fields)
