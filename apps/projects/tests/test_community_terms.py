import pytest
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.projects.enums import ProjectStatus
from apps.projects.models import CommunityTermsAcceptance
from apps.projects.services import (
    COMMUNITY_TERMS_VERSION,
    ProjectLifecycleError,
    accept_community_terms,
    current_community_terms_version,
    has_accepted_community_terms,
    open_personal_listing,
)
from apps.projects.tests.factories import PersonalProjectFactory, UserFactory

pytestmark = pytest.mark.django_db


@pytest.mark.unit
def test_terms_default_to_unaccepted_and_acceptance_is_versioned():
    """PPR-006: members start without acceptance; accepting records the version and timestamp."""
    member = UserFactory()
    assert has_accepted_community_terms(member) is False
    assert current_community_terms_version() == COMMUNITY_TERMS_VERSION

    acceptance = accept_community_terms(member)

    assert acceptance.version == COMMUNITY_TERMS_VERSION
    assert acceptance.accepted_at is not None
    assert has_accepted_community_terms(member) is True
    assert not has_accepted_community_terms(member, version="0000.00")


@pytest.mark.unit
def test_accepting_twice_is_idempotent_and_audited_once():
    """PPR-006: re-accepting the current version creates no duplicate or duplicate audit row."""
    member = UserFactory()

    first = accept_community_terms(member)
    second = accept_community_terms(member)

    assert first.pk == second.pk
    assert CommunityTermsAcceptance.objects.filter(user=member).count() == 1
    assert (
        AuditEvent.objects.filter(
            action="project.community_terms_accepted", object_id=str(first.pk)
        ).count()
        == 1
    )


@pytest.mark.integration
def test_publishing_personal_project_is_blocked_without_terms_acceptance():
    """PPR-006: the publish service refuses owners who have not accepted the community terms."""
    owner = UserFactory()
    project = PersonalProjectFactory(owner=owner, summary_en="A community project.")

    with pytest.raises(ProjectLifecycleError) as excinfo:
        open_personal_listing(owner, project)

    assert "community terms" in str(excinfo.value).lower()
    project.refresh_from_db()
    assert project.status == ProjectStatus.DRAFT

    accept_community_terms(owner)
    open_personal_listing(owner, project)
    project.refresh_from_db()
    assert project.status == ProjectStatus.OPEN_FOR_CONTRIBUTION


@pytest.mark.integration
def test_dashboard_offers_terms_acceptance_with_version_display(client):
    """PPR-006: the community dashboard shows the current terms version and an accept action."""
    member = UserFactory()
    client.force_login(member)
    dashboard_url = reverse("projects:community_dashboard")

    response = client.get(dashboard_url)

    assert response.status_code == 200
    assert COMMUNITY_TERMS_VERSION.encode() in response.content
    assert b"Accept community terms" in response.content

    response = client.post(reverse("projects:community_accept_terms"))

    assert response.status_code == 302
    assert response.url == dashboard_url
    assert has_accepted_community_terms(member)

    response = client.get(dashboard_url)
    assert b"You have accepted the current community terms." in response.content


@pytest.mark.integration
def test_publishing_through_the_ui_requires_accepted_terms(client):
    """PPR-006/PPR-001: the workflow view surfaces the terms gate as a 400 with a message."""
    owner = UserFactory()
    project = PersonalProjectFactory(owner=owner, summary_en="A community project.")
    client.force_login(owner)
    workflow_url = reverse("projects:community_workflow", kwargs={"slug": project.slug})

    response = client.post(workflow_url, {"action": "publish"})

    assert response.status_code == 400
    assert b"community terms" in response.content
    project.refresh_from_db()
    assert project.status == ProjectStatus.DRAFT

    assert client.post(reverse("projects:community_accept_terms")).status_code == 302
    assert client.post(workflow_url, {"action": "publish"}).status_code == 302
    project.refresh_from_db()
    assert project.status == ProjectStatus.OPEN_FOR_CONTRIBUTION


@pytest.mark.integration
def test_terms_acceptance_route_is_post_only(client):
    """PPR-006: acceptance is a state-changing action and only reachable by POST."""
    member = UserFactory()
    client.force_login(member)

    assert client.get(reverse("projects:community_accept_terms")).status_code == 405
