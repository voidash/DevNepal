import pytest
from django.contrib.messages import get_messages
from django.core.cache import cache
from django.test import Client, override_settings
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.github_sync.enums import SyncState
from apps.github_sync.errors import GithubAppResponseError
from apps.github_sync.models import GithubIssueSnapshot
from apps.github_sync.tests.factories import RepositoryConnectionFactory
from apps.github_sync.tests.test_public_repository_snapshot import SnapshotClient
from apps.ministries.tests.factories import MinistryPublisherFactory
from apps.projects.enums import ProjectStatus
from apps.projects.tests.factories import ProjectFactory

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


@pytest.fixture(autouse=True)
def clear_live_refresh_cache():
    cache.clear()
    yield
    cache.clear()


def publisher_repository():
    assignment = MinistryPublisherFactory()
    project = ProjectFactory(
        owner=assignment.user,
        ministry=assignment.ministry,
        status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
    )
    repository = RepositoryConnectionFactory(
        project=project,
        full_name="voidash/civic-help-directory",
        is_public=True,
        deactivated_at=None,
        sync_state=SyncState.IDLE,
    )
    return assignment, project, repository


def refresh_url(project, repository):
    return reverse(
        "github_sync:refresh_project_repository_snapshot",
        args=[project.slug, repository.pk],
    )


@override_settings(PRIVILEGED_MFA_BYPASS=True)
def test_git_003_publisher_refreshes_its_public_repository_from_github_app(client, monkeypatch):
    """GIT-003/GIT-010: publisher POST refreshes the exact public repository snapshot."""
    assignment, project, repository = publisher_repository()
    monkeypatch.setattr("apps.github_sync.views.github_app_client", lambda: SnapshotClient())
    client.force_login(assignment.user)

    workspace = client.get(reverse("projects:authoring_detail", args=[project.slug]))
    assert f'action="{refresh_url(project, repository)}"' in workspace.content.decode()
    assert "Refresh GitHub activity" in workspace.content.decode()

    response = client.post(refresh_url(project, repository))

    assert response.status_code == 302
    assert response.url == reverse("projects:authoring_detail", args=[project.slug])
    repository.refresh_from_db()
    assert repository.public_snapshot_at is not None
    assert GithubIssueSnapshot.objects.get(repository=repository).title == "Translate form"
    audit = AuditEvent.objects.get(action="github.public_snapshot.refresh")
    assert audit.actor == assignment.user
    assert audit.object_id == str(repository.pk)
    assert audit.after == {"issues": 1, "pull_requests": 1, "contributors": 1}
    followed = client.get(response.url)
    assert any(
        "GitHub activity refreshed" in str(message)
        for message in get_messages(followed.wsgi_request)
    )


@override_settings(PRIVILEGED_MFA_BYPASS=True)
def test_auth_006_refresh_hides_foreign_private_stopped_and_deactivated_repositories(
    client, monkeypatch
):
    """AUTH-006/SEC-005: ineligible repository targets do not disclose their existence."""
    assignment, project, repository = publisher_repository()
    foreign_assignment = MinistryPublisherFactory()
    calls = []
    monkeypatch.setattr(
        "apps.github_sync.views.refresh_public_repository_snapshot",
        lambda connection, provider: calls.append(connection),
    )

    client.force_login(foreign_assignment.user)
    assert client.post(refresh_url(project, repository)).status_code == 404

    client.force_login(assignment.user)
    for changes in (
        {"is_public": False},
        {"is_public": True, "sync_state": SyncState.STOPPED},
        {"sync_state": SyncState.IDLE, "deactivated_at": repository.created_at},
    ):
        for field, value in changes.items():
            setattr(repository, field, value)
        repository.save(update_fields=list(changes))
        assert client.post(refresh_url(project, repository)).status_code == 404
    assert calls == []


@override_settings(PRIVILEGED_MFA_BYPASS=True)
def test_sec_006_live_refresh_coalesces_repository_requests(client, monkeypatch):
    """SEC-006/GIT-003: a repository-wide cooldown prevents provider fan-out."""
    assignment, project, repository = publisher_repository()
    calls = []
    monkeypatch.setattr("apps.github_sync.views.github_app_client", lambda: SnapshotClient())
    monkeypatch.setattr(
        "apps.github_sync.views.refresh_public_repository_snapshot",
        lambda connection, provider: (
            calls.append(connection)
            or type(
                "Outcome",
                (),
                {"issues": 1, "pull_requests": 1, "contributors": 1},
            )()
        ),
    )
    client.force_login(assignment.user)

    first = client.post(refresh_url(project, repository))
    second = client.post(refresh_url(project, repository))

    assert first.status_code == 302
    assert second.status_code == 429
    assert 1 <= int(second.headers["Retry-After"]) <= 60
    assert calls == [repository]
    assert AuditEvent.objects.filter(action="github.public_snapshot.refresh_rate_limited").exists()


class FailingSnapshotClient(SnapshotClient):
    def repository_metadata(self, installation_id, full_name):
        raise GithubAppResponseError("secret provider detail")


@override_settings(PRIVILEGED_MFA_BYPASS=True)
def test_git_010_refresh_failure_keeps_last_good_snapshot_and_returns_safe_error(
    client, monkeypatch
):
    """GIT-010/SEC-008: provider failure preserves data and records a safe denial audit."""
    assignment, project, repository = publisher_repository()
    old_issue = GithubIssueSnapshot.objects.create(
        repository=repository,
        github_issue_id=99,
        number=99,
        title="Last known public issue",
        state="open",
        url="https://github.com/voidash/civic-help-directory/issues/99",
    )
    monkeypatch.setattr("apps.github_sync.views.github_app_client", lambda: FailingSnapshotClient())
    client.force_login(assignment.user)

    response = client.post(refresh_url(project, repository))

    content = response.content.decode()
    assert response.status_code == 503
    assert "GitHub could not be reached" in content
    assert "secret provider detail" not in content
    assert GithubIssueSnapshot.objects.filter(pk=old_issue.pk).exists()
    repository.refresh_from_db()
    assert repository.public_snapshot_note
    audit = AuditEvent.objects.get(action="github.public_snapshot.refresh_failed")
    assert audit.result == "failure"
    assert "secret provider detail" not in str(audit.after)


@override_settings(PRIVILEGED_MFA_BYPASS=True)
def test_live_refresh_requires_post_login_and_csrf(monkeypatch):
    """AUTH-006/SEC-004: live refresh rejects anonymous, GET, and missing-CSRF requests."""
    assignment, project, repository = publisher_repository()
    monkeypatch.setattr("apps.github_sync.views.github_app_client", lambda: SnapshotClient())
    url = refresh_url(project, repository)

    anonymous = Client()
    assert anonymous.post(url).status_code == 302

    client = Client(enforce_csrf_checks=True)
    client.force_login(assignment.user)
    assert client.get(url).status_code == 405
    assert client.post(url).status_code == 403
