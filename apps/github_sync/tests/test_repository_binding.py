import sys
import types

import pytest
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.github_sync.enums import ProcessingState
from apps.github_sync.errors import RepositoryBindingError
from apps.github_sync.models import RepositoryConnection
from apps.github_sync.services import bind_repository, process_pending
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
from apps.projects.tests.factories import PersonalProjectFactory, ProjectFactory

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


@pytest.fixture(autouse=True)
def github_sync_urlconf(settings):
    settings.ROOT_URLCONF = "apps.github_sync.tests.urls"


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


def test_publisher_project_filter_lists_exact_org_repository(client, settings):
    """GIT-003/AUTH-006: project-scoped listing permits its org repo without leaking others."""
    publisher = MinistryPublisherFactory()
    connection = GithubConnectionFactory(user=publisher.user, login="deepak")
    project = ProjectFactory(
        ministry=publisher.ministry,
        repository_url="https://github.com/dhm-np/flood-alert-gateway",
    )
    settings.GITHUB_APP_ID = "987654"
    settings.GITHUB_APP_PRIVATE_KEY = TEST_APP_KEY_PEM
    settings.PRIVILEGED_MFA_BYPASS = True

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

    settings.GITHUB_APP_TRANSPORT = transport
    client.force_login(connection.user)

    response = client.get(
        reverse("github_sync:connect_repository"), {"project_id": str(project.pk)}
    )

    assert response.status_code == 200
    assert [choice.full_name for choice in response.context["repositories"]] == [
        "dhm-np/flood-alert-gateway"
    ]
    assert "foreign-org/secret" not in response.content.decode()

    response = client.post(
        reverse("github_sync:connect_repository"),
        {
            "project_id": str(project.pk),
            "installation_id": "42",
            "repository_id": "1001",
        },
    )

    assert response.status_code == 302
    repository = RepositoryConnection.objects.get(repository_id=1001)
    assert repository.project == project
    assert repository.activated_by == publisher.user


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
