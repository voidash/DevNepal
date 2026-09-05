import pytest
from django.test import Client
from django.urls import reverse

from apps.projects.enums import ProjectStatus, ProjectType
from apps.projects.models import Project
from apps.projects.tests.factories import PersonalProjectFactory, UserFactory

pytestmark = pytest.mark.django_db


@pytest.mark.integration
def test_member_without_ministry_assignment_creates_and_edits_community_draft(client):
    """PPR-001/PPR-002: any authenticated member creates and edits a ministry-free listing."""
    owner = UserFactory()
    client.force_login(owner)

    response = client.post(
        reverse("projects:community_create"),
        {
            "title_en": "Open Transit Map",
            "summary_en": "A map for local transit routes.",
            "description_md": "Community-maintained route data.",
            "role": "Maintainer",
            "repository_url": "https://github.com/example/transit-map",
        },
    )

    project = Project.objects.get(title_en="Open Transit Map")
    assert response.status_code == 302
    assert response.url == reverse("projects:community_edit", kwargs={"slug": project.slug})
    assert project.project_type == ProjectType.PERSONAL
    assert project.owner == owner
    assert project.ministry_id is None
    assert project.status == ProjectStatus.DRAFT

    response = client.post(
        reverse("projects:community_edit", kwargs={"slug": project.slug}),
        {
            "title_en": "Open Transit Map",
            "summary_en": "An open map for local transit routes.",
            "description_md": "Community-maintained route data.",
            "role": "Lead maintainer",
            "repository_url": "https://github.com/example/transit-map",
        },
    )

    assert response.status_code == 302
    project.refresh_from_db()
    assert project.summary_en == "An open map for local transit routes."
    assert project.role == "Lead maintainer"


@pytest.mark.integration
def test_owner_publishes_unpublishes_and_archives_community_listing(client):
    """PPR-001/PPR-006: an owner who accepted the terms publishes, unpublishes, and archives."""
    owner = UserFactory()
    project = PersonalProjectFactory(owner=owner, summary_en="A useful community project.")
    client.force_login(owner)
    assert client.post(reverse("projects:community_accept_terms")).status_code == 302
    workflow_url = reverse("projects:community_workflow", kwargs={"slug": project.slug})

    for action, status in (
        ("publish", ProjectStatus.OPEN_FOR_CONTRIBUTION),
        ("unpublish", ProjectStatus.DRAFT),
        ("publish", ProjectStatus.OPEN_FOR_CONTRIBUTION),
        ("archive", ProjectStatus.ARCHIVED),
    ):
        response = client.post(workflow_url, {"action": action})
        assert response.status_code == 302
        project.refresh_from_db()
        assert project.status == status


@pytest.mark.integration
def test_community_authoring_hides_foreign_owner_records_and_rejects_csrf():
    """AUTH-006/PPR-001: community authoring is owner-scoped and lifecycle POSTs require CSRF."""
    owner = UserFactory()
    project = PersonalProjectFactory(owner=owner, summary_en="A useful community project.")
    foreign_owner = UserFactory()
    client = Client(enforce_csrf_checks=True)
    client.force_login(foreign_owner)

    assert (
        client.get(reverse("projects:community_edit", kwargs={"slug": project.slug})).status_code
        == 404
    )
    assert (
        client.post(
            reverse("projects:community_workflow", kwargs={"slug": project.slug}),
            {"action": "publish"},
        ).status_code
        == 403
    )
