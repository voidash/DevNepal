import pytest
from django.test import override_settings
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.ministries.tests.factories import MinistryPublisherFactory, UserFactory
from apps.projects.enums import ProjectStatus
from apps.projects.services import ProjectAuthorizationError, publish_by_publisher
from apps.projects.tests.factories import make_publishable

pytestmark = [pytest.mark.django_db]


def test_gov_004_publisher_can_publish_a_repository_backed_draft_without_super_admin():
    """GOV-004: an owning publisher can publish a ready GitHub-backed project directly."""
    project = make_publishable()

    published = publish_by_publisher(project.owner, project)

    published.refresh_from_db()
    assert published.status == ProjectStatus.OPEN_FOR_CONTRIBUTION
    assert published.current_version is not None
    assert published.current_version.published_by == project.owner
    assert published.reviews.get().decision == "published"
    assert AuditEvent.objects.filter(
        action="project.publisher_published", object_id=str(project.pk)
    )


def test_gov_001_foreign_publisher_cannot_publish_another_ministrys_draft():
    """GOV-001: direct publication stays scoped to the publisher's own ministry."""
    project = make_publishable()
    foreign = UserFactory()
    MinistryPublisherFactory(user=foreign)

    with pytest.raises(ProjectAuthorizationError):
        publish_by_publisher(foreign, project)

    project.refresh_from_db()
    assert project.status == ProjectStatus.DRAFT
    assert AuditEvent.objects.filter(action="project.publisher_publish.denied", result="failure")


@override_settings(PRIVILEGED_MFA_BYPASS=True)
def test_gov_004_publisher_workflow_exposes_direct_publish(client):
    """GOV-004: the ministry authoring UI replaces PMO submission with direct publication."""
    project = make_publishable()
    client.force_login(project.owner)

    detail = client.get(reverse("projects:authoring_detail", kwargs={"slug": project.slug}))

    assert detail.status_code == 200
    assert ("publish", "Publish") in detail.context["workflow_form"].fields["action"].choices
    assert b"Super Admin" not in detail.content
