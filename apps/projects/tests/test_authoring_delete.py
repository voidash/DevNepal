import pytest
from django.test import override_settings
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.github_sync.tests.factories import RepositoryConnectionFactory
from apps.ministries.tests.factories import MinistryPublisherFactory
from apps.projects.enums import ProjectStatus
from apps.projects.models import Project
from apps.projects.tests.factories import ProjectFactory

pytestmark = pytest.mark.django_db


@override_settings(PRIVILEGED_MFA_BYPASS=True)
def test_publisher_can_delete_only_their_unconnected_draft(client):
    """GOV-001/SEC-008: the draft delete control is POST-only, scoped and audited."""
    publisher = MinistryPublisherFactory()
    project = ProjectFactory(owner=publisher.user, ministry=publisher.ministry)
    client.force_login(publisher.user)

    page = client.get(reverse("projects:authoring_detail", args=[project.slug]))
    dashboard = client.get(reverse("projects:authoring_dashboard"))
    deleted = client.post(reverse("projects:authoring_delete", args=[project.slug]))

    assert page.status_code == 200
    assert dashboard.status_code == 200
    assert reverse("projects:authoring_delete", args=[project.slug]) in page.content.decode()
    assert reverse("projects:authoring_delete", args=[project.slug]) in dashboard.content.decode()
    assert deleted.status_code == 302
    assert deleted.url == reverse("projects:authoring_dashboard")
    assert not Project.objects.filter(pk=project.pk).exists()
    assert AuditEvent.objects.filter(
        action="project.draft_deleted", object_id=str(project.pk)
    ).exists()


@override_settings(PRIVILEGED_MFA_BYPASS=True)
@pytest.mark.parametrize("blocked_by", ["published", "repository"])
def test_draft_delete_refuses_non_drafts_and_connected_drafts(client, blocked_by):
    """GOV-001/GIT-003: delete never removes public work or a repository binding."""
    publisher = MinistryPublisherFactory()
    project = ProjectFactory(owner=publisher.user, ministry=publisher.ministry)
    if blocked_by == "published":
        project.status = ProjectStatus.OPEN_FOR_CONTRIBUTION
        project.save(update_fields=["status"])
    else:
        RepositoryConnectionFactory(project=project)
    client.force_login(publisher.user)

    response = client.post(reverse("projects:authoring_delete", args=[project.slug]))

    assert response.status_code == 302
    assert response.url == reverse("projects:authoring_detail", args=[project.slug])
    assert Project.objects.filter(pk=project.pk).exists()
    assert not AuditEvent.objects.filter(action="project.draft_deleted").exists()


@override_settings(PRIVILEGED_MFA_BYPASS=True)
def test_connected_draft_dashboard_does_not_offer_destructive_delete(client):
    """GIT-003: the dashboard never offers deletion while a repository is connected."""
    publisher = MinistryPublisherFactory()
    project = ProjectFactory(owner=publisher.user, ministry=publisher.ministry)
    RepositoryConnectionFactory(project=project)
    client.force_login(publisher.user)

    response = client.get(reverse("projects:authoring_dashboard"))

    assert response.status_code == 200
    delete_url = reverse("projects:authoring_delete", args=[project.slug])
    assert delete_url not in response.content.decode()
