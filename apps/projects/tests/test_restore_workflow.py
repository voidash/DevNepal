import pytest
from django.urls import reverse
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.projects.enums import ProjectStatus
from apps.projects.tests.factories import SuperAdminFactory, UserFactory, make_publishable

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


def _archive_via_workflow(client, project, super_admin):
    workflow_url = reverse("projects:authoring_workflow", kwargs={"slug": project.slug})
    verify_mfa(client, project.owner)
    assert client.post(workflow_url, {"action": "submit"}).status_code == 302
    verify_mfa(client, super_admin)
    assert client.post(workflow_url, {"action": "approve"}).status_code == 302
    assert client.post(workflow_url, {"action": "publish"}).status_code == 302
    verify_mfa(client, project.owner)
    assert client.post(workflow_url, {"action": "archive"}).status_code == 302
    project.refresh_from_db()
    assert project.status == ProjectStatus.ARCHIVED
    return workflow_url


@pytest.mark.integration
def test_super_admin_restores_archived_project_to_prior_public_state(client):
    """GOV-004: a Super Admin restores an archived project to its pre-archive public state."""
    project = make_publishable()
    super_admin = SuperAdminFactory()
    workflow_url = _archive_via_workflow(client, project, super_admin)

    verify_mfa(client, super_admin)
    detail = client.get(reverse("projects:authoring_detail", kwargs={"slug": project.slug}))
    assert b'value="restore"' in detail.content

    response = client.post(workflow_url, {"action": "restore"})

    assert response.status_code == 302
    project.refresh_from_db()
    assert project.status == ProjectStatus.OPEN_FOR_CONTRIBUTION
    assert project.archived_at is None


@pytest.mark.integration
def test_restored_project_accepts_applications_again(client):
    """BR-011: an archived project accepts no applications; restoring reopens the pipeline."""
    project = make_publishable()
    super_admin = SuperAdminFactory()
    workflow_url = _archive_via_workflow(client, project, super_admin)

    applicant = UserFactory()
    client.force_login(applicant)
    apply_url = reverse("projects:apply", kwargs={"slug": project.slug})
    assert client.post(apply_url, {"motivation": "Interested."}).status_code == 400

    verify_mfa(client, super_admin)
    assert client.post(workflow_url, {"action": "restore"}).status_code == 302
    assert client.post(apply_url, {"motivation": "Interested."}).status_code == 302


@pytest.mark.integration
def test_owning_publisher_cannot_restore_archived_project(client):
    """GOV-004/AUTH-006: restore is never offered to or executable by ministry publishers."""
    project = make_publishable()
    super_admin = SuperAdminFactory()
    workflow_url = _archive_via_workflow(client, project, super_admin)

    detail = client.get(reverse("projects:authoring_detail", kwargs={"slug": project.slug}))
    response = client.post(workflow_url, {"action": "restore"})

    project.refresh_from_db()
    assert detail.status_code == 200
    assert b'value="restore"' not in detail.content
    assert response.status_code == 400
    assert project.status == ProjectStatus.ARCHIVED
