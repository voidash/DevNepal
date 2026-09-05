import pytest
from django.test import Client
from django.urls import reverse
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.ministries.tests.factories import MinistryPublisherFactory
from apps.projects.enums import ProjectStatus
from apps.projects.models import (
    SUITABILITY_AREAS,
    Project,
    ProjectMilestone,
    ProjectSuitability,
    ProjectTask,
)
from apps.projects.tests.factories import SuperAdminFactory, make_publishable

pytestmark = pytest.mark.django_db


def verify_mfa(client, user):
    client.force_login(user)
    setup_url = reverse("accounts:mfa_setup")
    assert client.get(setup_url).status_code == 200
    device = TOTPDevice.objects.get(user=user)
    device.last_t = -1
    device.save(update_fields=["last_t"])
    token = totp(
        device.bin_key,
        step=device.step,
        t0=device.t0,
        digits=device.digits,
        drift=device.drift,
    )
    response = client.post(setup_url, {"token": token})
    assert response.status_code == 302


@pytest.mark.integration
def test_publisher_creates_a_ministry_owned_draft_through_authoring_ui(client):
    """GOV-001/GOV-002: an MFA-verified publisher creates a bilingual draft only in its ministry."""
    assignment = MinistryPublisherFactory()
    verify_mfa(client, assignment.user)

    response = client.post(
        reverse("projects:authoring_create"),
        {
            "ministry": assignment.ministry.pk,
            "title_en": "Digital Service Directory",
            "title_ne": "डिजिटल सेवा निर्देशिका",
            "summary_en": "A directory for public services.",
            "summary_ne": "सार्वजनिक सेवाहरूको निर्देशिका।",
            "data_classification": "public",
        },
    )

    project = Project.objects.get(title_en="Digital Service Directory")
    assert response.status_code == 302
    assert response.url == reverse("projects:authoring_edit", kwargs={"slug": project.slug})
    assert project.project_type == "government"
    assert project.ministry == assignment.ministry
    assert project.owner == assignment.user
    assert project.status == ProjectStatus.DRAFT


@pytest.mark.integration
def test_authoring_detail_hides_foreign_ministry_projects(client):
    """GOV-001/AUTH-006: a publisher cannot view or edit another ministry's draft."""
    project = make_publishable()
    foreign_publisher = MinistryPublisherFactory()
    verify_mfa(client, foreign_publisher.user)

    response = client.get(reverse("projects:authoring_edit", kwargs={"slug": project.slug}))

    assert response.status_code == 404


@pytest.mark.integration
def test_authoring_workflow_reaches_every_requested_lifecycle_action(client):
    """GOV-004/GOV-005: publisher and Super Admin can reach each requested lifecycle action."""
    project = make_publishable()
    publisher = project.owner
    super_admin = SuperAdminFactory()
    workflow_url = reverse("projects:authoring_workflow", kwargs={"slug": project.slug})

    verify_mfa(client, publisher)
    assert client.post(workflow_url, {"action": "submit"}).status_code == 302
    project.refresh_from_db()
    assert project.status == ProjectStatus.IN_REVIEW

    verify_mfa(client, super_admin)
    assert (
        client.post(
            workflow_url, {"action": "request_changes", "reason": "Clarify scope."}
        ).status_code
        == 302
    )
    project.refresh_from_db()
    assert project.status == ProjectStatus.CHANGES_REQUESTED

    verify_mfa(client, publisher)
    assert client.post(workflow_url, {"action": "resubmit"}).status_code == 302
    project.refresh_from_db()
    assert project.status == ProjectStatus.IN_REVIEW

    verify_mfa(client, super_admin)
    assert client.post(workflow_url, {"action": "approve"}).status_code == 302
    assert client.post(workflow_url, {"action": "publish"}).status_code == 302
    project.refresh_from_db()
    assert project.status == ProjectStatus.OPEN_FOR_CONTRIBUTION

    verify_mfa(client, publisher)
    for action, status in (
        ("pause", ProjectStatus.PAUSED),
        ("resume", ProjectStatus.OPEN_FOR_CONTRIBUTION),
        ("complete", ProjectStatus.COMPLETED),
        ("archive", ProjectStatus.ARCHIVED),
    ):
        assert client.post(workflow_url, {"action": action}).status_code == 302
        project.refresh_from_db()
        assert project.status == status


@pytest.mark.integration
def test_authoring_workflow_rejects_csrf_and_requires_an_mfa_session():
    """AUTH-005/AUTH-006/SEC-004: lifecycle POSTs reject CSRF and unverified publisher sessions."""
    project = make_publishable()
    client = Client(enforce_csrf_checks=True)
    client.force_login(project.owner)
    workflow_url = reverse("projects:authoring_workflow", kwargs={"slug": project.slug})

    csrf_rejected = client.post(workflow_url, {"action": "submit"})
    mfa_redirect = client.get(workflow_url)

    project.refresh_from_db()
    assert csrf_rejected.status_code == 403
    assert mfa_redirect.status_code == 302
    assert mfa_redirect.url == reverse("accounts:mfa_setup")
    assert project.status == ProjectStatus.DRAFT


@pytest.mark.integration
def test_publisher_manages_maintainers_tasks_milestones_and_suitability(client):
    """GOV-001/GOV-002/GOV-007: an MFA-verified publisher authors readiness records."""
    project = make_publishable()
    verify_mfa(client, project.owner)
    manage_url = reverse("projects:authoring_manage", kwargs={"slug": project.slug})

    response = client.post(
        manage_url,
        {
            "action": "maintainer",
            "user": project.owner.pk,
            "role": "lead",
            "can_review_merge": "on",
        },
    )
    assert response.status_code == 302
    assert project.maintainer_assignments.filter(
        user=project.owner, role="lead", can_review_merge=True
    ).exists()

    response = client.post(
        manage_url,
        {
            "action": "task",
            "title": "Publish contribution guide",
            "description": "Document the contribution path.",
            "is_starter": "on",
            "issue_url": "https://github.com/moit/service-directory/issues/42",
            "status": "open",
        },
    )
    assert response.status_code == 302
    assert ProjectTask.objects.filter(project=project, title="Publish contribution guide").exists()

    response = client.post(
        manage_url,
        {
            "action": "milestone",
            "title": "Pilot release",
            "description": "Release the first pilot.",
            "due_date": "2027-01-15",
            "status": "planned",
            "sort_order": "1",
        },
    )
    assert response.status_code == 302
    assert ProjectMilestone.objects.filter(project=project, title="Pilot release").exists()

    response = client.post(
        manage_url,
        {
            "action": "suitability",
            "legal_authority": "on",
            "source_code_rights": "on",
            "data_classification": "on",
            "security_exposure": "on",
            "procurement_restrictions": "on",
            "third_party_licenses": "on",
            "repository_readiness": "on",
            "maintainer_capacity": "on",
            "contribution_agreement": "on",
            "public_communications": "on",
            "notes": "Reviewed by the ministry legal officer.",
        },
    )
    assert response.status_code == 302
    suitability = ProjectSuitability.objects.get(project=project)
    assert suitability.completed_by == project.owner
    assert suitability.completed_at is not None
    assert suitability.checklist["repository_readiness"]["checked"] is True


@pytest.mark.integration
def test_super_admin_confirms_suitability_and_sees_publish_readiness_evidence(client):
    """BR-002/BR-003: an MFA-verified Super Admin confirms suitability and sees evidence."""
    project = make_publishable()
    super_admin = SuperAdminFactory()
    verify_mfa(client, super_admin)
    manage_url = reverse("projects:authoring_manage", kwargs={"slug": project.slug})

    checklist = {area: "on" for area in SUITABILITY_AREAS}
    checklist["action"] = "suitability"
    assert client.post(manage_url, checklist).status_code == 302
    response = client.post(manage_url, {"action": "confirm_suitability"})

    assert response.status_code == 302
    assert ProjectSuitability.objects.get(project=project).confirmed_by == super_admin
    detail = client.get(reverse("projects:authoring_readiness", kwargs={"slug": project.slug}))
    assert detail.status_code == 200
    assert b"Publish readiness" in detail.content
    assert b"Ready for publication" in detail.content


@pytest.mark.integration
def test_authoring_management_hides_foreign_projects_and_requires_mfa(client):
    """GOV-001/AUTH-006: management actions are ministry-scoped and MFA-gated."""
    project = make_publishable()
    foreign_publisher = MinistryPublisherFactory()
    manage_url = reverse("projects:authoring_manage", kwargs={"slug": project.slug})

    client.force_login(foreign_publisher.user)
    assert client.post(manage_url, {"action": "task", "title": "Foreign task"}).status_code == 302

    verify_mfa(client, foreign_publisher.user)
    assert client.post(manage_url, {"action": "task", "title": "Foreign task"}).status_code == 404
