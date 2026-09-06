import sys
import types
from types import SimpleNamespace

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.github_sync.enums import ProcessingState
from apps.github_sync.errors import GithubAppError, RepositoryBindingError
from apps.github_sync.models import RepositoryConnection
from apps.github_sync.services import bind_repository, process_pending, rebind_repository_for_demo
from apps.github_sync.tests.data import TEST_APP_KEY_PEM
from apps.github_sync.tests.factories import (
    GithubConnectionFactory,
    ProviderEventFactory,
    RepositoryConnectionFactory,
)
from apps.ministries.tests.factories import (
    MinistryOrganizationFactory,
    MinistryPublisherFactory,
    SuperAdminFactory,
    UserFactory,
)
from apps.projects.enums import ProjectStatus
from apps.projects.tests.factories import PersonalProjectFactory, ProjectFactory
from apps.taxonomy.tests.factories import ApprovedLicenseFactory

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


@pytest.fixture(autouse=True)
def github_sync_urlconf(settings):
    settings.ROOT_URLCONF = "apps.github_sync.tests.urls"


def publisher_repository_transport():
    def transport(request):
        url = request["url"]
        if "/app/installations?" in url:
            return 200, [
                {
                    "id": 42,
                    "account": {"login": "dhm-np"},
                    "permissions": {"metadata": "read"},
                },
                {
                    "id": 43,
                    "account": {"login": "foreign-org"},
                    "permissions": {"metadata": "read"},
                },
            ]
        if url.endswith("/app/installations/42/access_tokens"):
            return 201, {"token": "token-for-dhm"}
        if url.endswith("/app/installations/43/access_tokens"):
            return 201, {"token": "token-for-foreign"}
        if "/installation/repositories?" in url:
            if request["headers"]["Authorization"] == "token token-for-dhm":
                return 200, {
                    "repositories": [
                        {
                            "id": 1001,
                            "node_id": "R_dhm",
                            "full_name": "dhm-np/flood-alert-gateway",
                            "private": False,
                            "owner": {"login": "dhm-np"},
                        }
                    ]
                }
            return 200, {
                "repositories": [
                    {
                        "id": 1002,
                        "node_id": "R_foreign",
                        "full_name": "foreign-org/secret",
                        "private": True,
                        "owner": {"login": "foreign-org"},
                    }
                ]
            }
        raise AssertionError(url)

    return transport


def test_ministry_publisher_binds_organization_repository_to_own_project():
    """GIT-001/GIT-003: an authorized publisher binds an enrolled organization repo."""
    publisher = MinistryPublisherFactory()
    project = ProjectFactory(
        ministry=publisher.ministry,
        repository_url="https://github.com/dhm-np/flood-alert-gateway",
    )
    repository = RepositoryConnectionFactory(
        project=None,
        full_name="dhm-np/flood-alert-gateway",
        activated_by=publisher.user,
    )

    outcome = bind_repository(publisher.user, repository, project)

    repository.refresh_from_db()
    assert outcome.connection == repository
    assert outcome.bound is True
    assert repository.project == project
    event = AuditEvent.objects.get(action="github_repository.bind_project")
    assert event.actor == publisher.user
    assert event.object_id == str(repository.pk)
    assert event.after["project_id"] == project.pk


def test_publisher_cannot_bind_repository_to_another_ministry_project():
    """AUTH-006/GIT-003: a publisher cannot bind a repository across ministries."""
    publisher = MinistryPublisherFactory()
    project = ProjectFactory(
        ministry=MinistryOrganizationFactory(),
        repository_url="https://github.com/other-org/service",
    )
    repository = RepositoryConnectionFactory(project=None, full_name="other-org/service")

    with pytest.raises(RepositoryBindingError):
        bind_repository(publisher.user, repository, project)

    repository.refresh_from_db()
    assert repository.project is None
    assert AuditEvent.objects.filter(action="github_repository.bind_project").count() == 0


def test_personal_project_owner_can_bind_only_their_enrolled_repository():
    """PPR-004/GIT-003: a member binds their enrolled repository only to their own listing."""
    owner = UserFactory()
    project = PersonalProjectFactory(
        owner=owner,
        repository_url="https://github.com/member/community-widget",
    )
    repository = RepositoryConnectionFactory(
        project=None,
        full_name="member/community-widget",
        activated_by=owner,
    )

    assert bind_repository(owner, repository, project).bound is True

    foreign_project = PersonalProjectFactory(
        owner=UserFactory(),
        repository_url="https://github.com/member/another-widget",
    )
    foreign_repository = RepositoryConnectionFactory(
        project=None,
        full_name="member/another-widget",
        activated_by=owner,
    )
    with pytest.raises(RepositoryBindingError):
        bind_repository(owner, foreign_repository, foreign_project)


def test_repository_cannot_be_rebound_or_bound_to_a_mismatched_url():
    """GIT-003: one repository association cannot be reassigned or forged by project id."""
    admin = SuperAdminFactory()
    first = ProjectFactory(repository_url="https://github.com/moit/service-directory")
    second = ProjectFactory(repository_url="https://github.com/moit/service-directory")
    mismatch = ProjectFactory(repository_url="https://github.com/moit/different")
    repository = RepositoryConnectionFactory(
        project=None,
        full_name="moit/service-directory",
        activated_by=admin,
    )

    assert bind_repository(admin, repository, first).bound is True
    assert bind_repository(admin, repository, first).bound is False
    with pytest.raises(RepositoryBindingError):
        bind_repository(admin, repository, second)

    other = RepositoryConnectionFactory(project=None, full_name="moit/service-directory-two")
    with pytest.raises(RepositoryBindingError):
        bind_repository(admin, other, mismatch)


def test_configured_demo_publisher_can_move_exact_repository_to_own_new_project(settings):
    """GOV-004/GIT-003: the rehearsal repository follows the newly named demo project."""
    publisher = MinistryPublisherFactory()
    previous = ProjectFactory(
        ministry=MinistryOrganizationFactory(),
        repository_url="https://github.com/voidash/nepali-sign-language-research",
    )
    created = ProjectFactory(
        owner=publisher.user,
        ministry=publisher.ministry,
        title_en="Accessible Research Workspace",
        repository_url="https://github.com/voidash/nepali-sign-language-research",
    )
    repository = RepositoryConnectionFactory(
        project=previous,
        full_name="voidash/nepali-sign-language-research",
        activated_by=publisher.user,
    )
    settings.DEMO_ONE_CLICK_PUBLISH_USERNAMES = [publisher.user.username]

    outcome = rebind_repository_for_demo(publisher.user, repository, created)

    repository.refresh_from_db()
    assert outcome.bound is True
    assert repository.project == created
    assert repository.project.title_en == "Accessible Research Workspace"


def test_publisher_connects_and_syncs_before_explicit_publication(client, settings, monkeypatch):
    """GIT-003/GIT-010/GOV-004: connection is visible before an explicit publish."""
    settings.ROOT_URLCONF = "config.urls"
    publisher = MinistryPublisherFactory()
    project = ProjectFactory(
        ready=True,
        ministry=publisher.ministry,
        repository_url="https://github.com/dhm-np/flood-alert-gateway",
    )
    project.license = ApprovedLicenseFactory(is_approved=True)
    project.save(update_fields=["license"])
    settings.GITHUB_APP_ID = "987654"
    settings.GITHUB_APP_PRIVATE_KEY = TEST_APP_KEY_PEM
    settings.PRIVILEGED_MFA_BYPASS = True
    settings.DEMO_ONE_CLICK_PUBLISH_USERNAMES = [publisher.user.username]
    refreshed = []

    def refresh_snapshot(repository, _client):
        refreshed.append(repository.pk)
        return SimpleNamespace(issues=4, pull_requests=2, contributors=3)

    monkeypatch.setattr(
        "apps.github_sync.views.refresh_public_repository_snapshot", refresh_snapshot
    )

    settings.GITHUB_APP_TRANSPORT = publisher_repository_transport()
    client.force_login(publisher.user)

    response = client.get(
        reverse("github_sync:connect_repository"), {"project_id": str(project.pk)}
    )

    assert response.status_code == 200
    assert response.context["uses_project_app_installation"] is True
    assert [choice.full_name for choice in response.context["repositories"]] == [
        "dhm-np/flood-alert-gateway"
    ]
    assert "foreign-org/secret" not in response.content.decode()

    response = client.post(
        reverse("github_sync:connect_repository"),
        {"project_id": str(project.pk)},
    )

    assert response.status_code == 302
    assert response.url == reverse("projects:authoring_detail", args=[project.slug])
    repository = RepositoryConnection.objects.get(repository_id=1001)
    assert repository.project == project
    assert repository.activated_by == publisher.user
    project.refresh_from_db()
    assert project.status == ProjectStatus.DRAFT
    assert refreshed == [repository.pk]
    assert client.get(reverse("projects:detail", args=[project.slug])).status_code == 404

    workspace = client.get(reverse("projects:authoring_detail", args=[project.slug]))
    content = workspace.content.decode()
    assert workspace.status_code == 200
    assert "Connected" in content
    assert "GitHub activity" in content
    assert 'name="action" value="publish"' in content

    published = client.post(
        reverse("projects:authoring_workflow", args=[project.slug]),
        {"action": "publish"},
    )
    project.refresh_from_db()
    assert published.status_code == 302
    assert published.url == reverse("projects:detail", args=[project.slug])
    assert project.status == ProjectStatus.OPEN_FOR_CONTRIBUTION
    assert client.get(published.url).status_code == 200

    project.ministry = MinistryOrganizationFactory()
    project.save(update_fields=["ministry", "updated_at"])
    duplicate = ProjectFactory(
        ready=True,
        ministry=publisher.ministry,
        repository_url="https://github.com/dhm-np/flood-alert-gateway",
    )
    duplicate.license = ApprovedLicenseFactory(is_approved=True)
    duplicate.save(update_fields=["license"])
    reused = client.post(
        reverse("github_sync:connect_repository"),
        {"project_id": str(duplicate.pk)},
    )

    assert reused.status_code == 302
    assert reused.url == reverse("projects:authoring_detail", args=[duplicate.slug])
    repository.refresh_from_db()
    duplicate.refresh_from_db()
    assert repository.project == duplicate
    assert repository.project.ministry == publisher.ministry
    assert duplicate.status == ProjectStatus.DRAFT
    assert refreshed == [repository.pk, repository.pk]


def test_initial_snapshot_failure_keeps_repository_bound_to_draft(client, settings, monkeypatch):
    """GIT-003/GIT-010: a GitHub outage never erases the binding or publishes the draft."""
    publisher = MinistryPublisherFactory()
    project = ProjectFactory(
        owner=publisher.user,
        ministry=publisher.ministry,
        repository_url="https://github.com/dhm-np/flood-alert-gateway",
    )
    settings.GITHUB_APP_ID = "987654"
    settings.GITHUB_APP_PRIVATE_KEY = TEST_APP_KEY_PEM
    settings.GITHUB_APP_TRANSPORT = publisher_repository_transport()
    settings.PRIVILEGED_MFA_BYPASS = True

    def fail_snapshot(_repository, _client):
        raise GithubAppError("temporary provider outage")

    monkeypatch.setattr("apps.github_sync.views.refresh_public_repository_snapshot", fail_snapshot)
    client.force_login(publisher.user)

    response = client.post(
        reverse("github_sync:connect_repository"),
        {"project_id": str(project.pk)},
    )

    repository = RepositoryConnection.objects.get(repository_id=1001)
    project.refresh_from_db()
    notices = [str(message) for message in get_messages(response.wsgi_request)]
    assert response.status_code == 302
    assert response.url == reverse("projects:authoring_detail", args=[project.slug])
    assert repository.project == project
    assert project.status == ProjectStatus.DRAFT
    assert notices == ["Repository connected, but GitHub activity could not be loaded. Try again."]
    assert client.get(reverse("projects:detail", args=[project.slug])).status_code == 404


def test_cross_ministry_project_filter_is_not_found(client, settings):
    """AUTH-006/GIT-003: project ids cannot expose another ministry's App repositories."""
    publisher = MinistryPublisherFactory()
    connection = GithubConnectionFactory(user=publisher.user)
    project = ProjectFactory(ministry=MinistryOrganizationFactory())
    settings.GITHUB_APP_ID = "987654"
    settings.GITHUB_APP_PRIVATE_KEY = TEST_APP_KEY_PEM
    settings.PRIVILEGED_MFA_BYPASS = True
    settings.GITHUB_APP_TRANSPORT = lambda request: (_ for _ in ()).throw(
        AssertionError("GitHub must not be called for an unauthorized project")
    )
    client.force_login(connection.user)

    response = client.get(
        reverse("github_sync:connect_repository"), {"project_id": str(project.pk)}
    )

    assert response.status_code == 404


def test_bound_repository_events_resolve_to_the_authorized_project(monkeypatch):
    """GIT-003/GIT-005: a new binding is the project mapping used by event processing."""
    publisher = MinistryPublisherFactory()
    project = ProjectFactory(
        ministry=publisher.ministry,
        repository_url="https://github.com/dhm-np/flood-alert-gateway",
    )
    repository = RepositoryConnectionFactory(
        project=None,
        full_name="dhm-np/flood-alert-gateway",
        activated_by=publisher.user,
    )
    bind_repository(publisher.user, repository, project)
    event = ProviderEventFactory(
        repository=repository,
        node_id=repository.repository_node_id,
    )
    calls = []
    contribution_services = types.ModuleType("apps.contributions.services")
    contribution_services.record_candidate_from_github = lambda parsed, mapped_project: (
        calls.append((parsed, mapped_project))
    )
    monkeypatch.setitem(sys.modules, "apps.contributions.services", contribution_services)

    result = process_pending(limit=10)

    event.refresh_from_db()
    assert result.processed == 1
    assert event.processing_state == ProcessingState.PROCESSED
    assert [mapped_project for _parsed, mapped_project in calls] == [project]
