import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.ministries.tests.factories import MinistryPublisherFactory
from apps.projects.enums import AttachmentKind, ScanStatus
from apps.projects.models import ProjectAttachment
from apps.projects.services import record_scan_result
from apps.projects.tests.factories import ProjectAttachmentFactory, make_publishable

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


def attachment_url(project):
    return reverse("projects:authoring_attachment", kwargs={"slug": project.slug})


def upload_payload(**overrides):
    payload = {
        "kind": AttachmentKind.PROPOSAL,
        "language": "en",
        "classification": "public",
        "accessibility_note": "Screen-reader friendly.",
        "file": SimpleUploadedFile(
            "proposal.pdf", b"%PDF-1.4 plan", content_type="application/pdf"
        ),
    }
    payload.update(overrides)
    return payload


@pytest.mark.integration
def test_publisher_uploads_proposal_with_pending_scan_status(client):
    """GOV-003: an MFA-verified publisher uploads an attachment recorded with pending scan."""
    project = make_publishable()
    verify_mfa(client, project.owner)

    response = client.post(attachment_url(project), upload_payload())

    assert response.status_code == 302
    attachment = ProjectAttachment.objects.get(project=project)
    assert attachment.original_filename == "proposal.pdf"
    assert attachment.kind == AttachmentKind.PROPOSAL
    assert attachment.scan == ScanStatus.PENDING
    assert attachment.version == 1
    assert attachment.uploaded_by == project.owner


@pytest.mark.integration
def test_attachment_route_rejects_executable_files(client):
    """GOV-003/SEC-007: the route refuses executable uploads through the service validation."""
    project = make_publishable()
    verify_mfa(client, project.owner)

    response = client.post(
        attachment_url(project),
        upload_payload(
            kind=AttachmentKind.OTHER,
            file=SimpleUploadedFile(
                "installer.exe", b"MZ", content_type="application/octet-stream"
            ),
        ),
    )

    assert response.status_code == 400
    assert not ProjectAttachment.objects.filter(project=project).exists()


@pytest.mark.integration
def test_attachment_route_is_csrf_and_mfa_gated(client):
    """GOV-003/AUTH-005/AUTH-006: CSRF-less and unverified sessions cannot attach files."""
    project = make_publishable()
    url = attachment_url(project)

    client.force_login(project.owner)
    unverified_get = client.get(url)
    assert unverified_get.status_code == 302
    assert unverified_get.url == reverse("accounts:mfa_setup")

    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(project.owner)
    assert csrf_client.post(url, upload_payload()).status_code == 403

    unverified_client = Client()
    unverified_client.force_login(project.owner)
    unverified_post = unverified_client.post(url, upload_payload())
    assert unverified_post.status_code == 302
    assert unverified_post.url == reverse("accounts:mfa_setup")
    assert not ProjectAttachment.objects.filter(project=project).exists()


@pytest.mark.integration
def test_foreign_publisher_cannot_upload_attachments(client):
    """GOV-003/AUTH-006: a publisher of another ministry receives 404 on the attachment route."""
    project = make_publishable()
    foreign_publisher = MinistryPublisherFactory()
    verify_mfa(client, foreign_publisher.user)

    response = client.post(attachment_url(project), upload_payload())

    assert response.status_code == 404
    assert not ProjectAttachment.objects.filter(project=project).exists()


@pytest.mark.integration
def test_authoring_detail_shows_scan_status_and_never_links_quarantined_files(client):
    """GOV-003/SEC-007: scan status is visible; quarantined files are never exposed for download."""
    project = make_publishable()
    clean = ProjectAttachmentFactory(
        project=project,
        kind=AttachmentKind.REQUIREMENTS,
        original_filename="requirements.txt",
        file=SimpleUploadedFile("requirements.txt", b"requirements", content_type="text/plain"),
    )
    record_scan_result(clean, ScanStatus.CLEAN)
    quarantined = ProjectAttachmentFactory(
        project=project,
        kind=AttachmentKind.PROPOSAL,
        original_filename="bad-proposal.pdf",
        file=SimpleUploadedFile(
            "bad-proposal.pdf", b"%PDF-1.4 bad", content_type="application/pdf"
        ),
    )
    record_scan_result(quarantined, ScanStatus.FAILED)
    verify_mfa(client, project.owner)

    response = client.get(attachment_url(project))

    assert response.status_code == 200
    content = response.content
    assert b"requirements.txt" in content
    assert b"bad-proposal.pdf" in content
    assert b"Clean" in content
    assert b"Quarantined" in content
    assert b"project-attachments" not in content
