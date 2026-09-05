import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.projects.enums import AttachmentKind, ScanStatus
from apps.projects.services import AttachmentError, add_attachment, record_scan_result
from apps.projects.tests.factories import (
    ProjectAttachmentFactory,
    ProjectFactory,
    ProjectScreeningQuestionFactory,
    ProjectSuitabilityFactory,
    ProjectTaskFactory,
    UserFactory,
    make_publishable,
)

pytestmark = [pytest.mark.django_db]

SUITABILITY_KEYS = [
    "legal_authority",
    "source_code_rights",
    "data_classification",
    "security_exposure",
    "procurement_restrictions",
    "third_party_licenses",
    "repository_readiness",
    "maintainer_capacity",
    "contribution_agreement",
    "public_communications",
]


@pytest.mark.unit
def test_attachment_records_file_metadata_and_pending_scan():
    """GOV-003: attachments record original filename, size, kind, and scan status."""
    attachment = ProjectAttachmentFactory(
        kind=AttachmentKind.PROPOSAL, original_filename="proposal.pdf", size_bytes=2048
    )
    fetched = type(attachment).objects.get(pk=attachment.pk)
    assert fetched.original_filename == "proposal.pdf"
    assert fetched.size_bytes == 2048
    assert fetched.scan == ScanStatus.PENDING
    assert fetched.version == 1
    assert fetched.language == "en"
    assert attachment.file.name


@pytest.mark.unit
def test_suitability_checklist_carries_ten_5_3_areas():
    """BR-002/SRS 5.3: the suitability checklist covers the ten mandated areas."""
    checklist = {key: {"checked": True, "note": ""} for key in SUITABILITY_KEYS}
    suitability = ProjectSuitabilityFactory(checklist=checklist)
    fetched = type(suitability).objects.get(pk=suitability.pk)
    assert sorted(fetched.checklist) == sorted(SUITABILITY_KEYS)
    assert fetched.project.suitability == fetched
    assert fetched.confirmed_at is None


@pytest.mark.unit
def test_screening_questions_are_project_scoped_and_ordered():
    """DSC-006: screening questions belong to a project, ordered and toggleable."""
    project = ProjectFactory()
    first = ProjectScreeningQuestionFactory(
        project=project, sort_order=1, question="Why this project?"
    )
    second = ProjectScreeningQuestionFactory(
        project=project, sort_order=2, question="Weekly hours?"
    )
    questions = list(project.screening_questions.all())
    assert questions == [first, second]
    assert first.is_required is True
    assert second.is_active is True


@pytest.mark.unit
def test_task_carries_starter_flag_and_issue_link():
    """GOV-007/BR-002: an actionable task links an issue and can be a starter task."""
    task = ProjectTaskFactory(is_starter=True, issue_url="https://github.com/org/repo/issues/1")
    assert task.is_starter is True
    assert task.status == "open"
    assert task.project.tasks.count() == 1


# ---------------------------------------------------------------------------
# Attachment services (GOV-003, SEC-007, SEC-004)


@pytest.mark.integration
def test_attachment_replacement_increments_version():
    """GOV-003-U2: uploading a new proposal supersedes the previous version."""
    project = make_publishable()
    first = add_attachment(
        project.owner,
        project,
        kind="proposal",
        file=SimpleUploadedFile("proposal-v1.pdf", b"%PDF-1.4 one", content_type="application/pdf"),
    )
    second = add_attachment(
        project.owner,
        project,
        kind="proposal",
        file=SimpleUploadedFile("proposal-v2.pdf", b"%PDF-1.4 two", content_type="application/pdf"),
    )
    assert first.version == 1
    assert second.version == 2
    assert project.attachments.filter(kind="proposal").count() == 2


@pytest.mark.integration
def test_attachment_storage_is_traversal_safe():
    """SEC-004-U3: hostile filenames cannot escape the private attachment path."""
    project = make_publishable()
    hostile = SimpleUploadedFile("../../etc/passwd", b"root:x:0:0", content_type="text/plain")
    attachment = add_attachment(project.owner, project, kind="other", file=hostile)
    assert ".." not in attachment.file.name
    assert attachment.file.name.startswith(f"project-attachments/{project.pk}/")


@pytest.mark.integration
def test_executable_uploads_are_rejected():
    """SEC-007-U1: executable extensions and oversized files are refused outright."""
    project = make_publishable()
    with pytest.raises(AttachmentError):
        add_attachment(
            project.owner,
            project,
            kind="other",
            file=SimpleUploadedFile(
                "installer.exe", b"MZ", content_type="application/octet-stream"
            ),
        )
    oversized = SimpleUploadedFile("huge.pdf", b"x" * 64, content_type="application/pdf")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("apps.projects.services.max_attachment_bytes", lambda: 8)
        with pytest.raises(AttachmentError):
            add_attachment(project.owner, project, kind="proposal", file=oversized)


@pytest.mark.integration
def test_scan_results_drive_serving_eligibility():
    """SEC-007/GOV-003: clean scans clear the file; failed scans quarantine and purge it."""
    project = make_publishable()
    attachment = add_attachment(
        project.owner,
        project,
        kind="requirements",
        file=SimpleUploadedFile("req.txt", b"requirements", content_type="text/plain"),
    )

    record_scan_result(attachment, ScanStatus.CLEAN)
    attachment.refresh_from_db()
    assert attachment.scan == ScanStatus.CLEAN
    assert attachment.file

    record_scan_result(attachment, ScanStatus.FAILED)
    attachment.refresh_from_db()
    assert attachment.scan == ScanStatus.QUARANTINED
    assert not attachment.file


@pytest.mark.integration
def test_attachment_upload_requires_ownership():
    """GOV-003/AUTH-006: only the owning publisher or a Super Admin attaches files."""
    project = make_publishable()
    with pytest.raises(Exception) as excinfo:
        add_attachment(
            UserFactory(),
            project,
            kind="proposal",
            file=SimpleUploadedFile("x.pdf", b"%PDF-1.4", content_type="application/pdf"),
        )
    from apps.projects.services import ProjectAuthorizationError

    assert isinstance(excinfo.value, ProjectAuthorizationError)
