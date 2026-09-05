import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.audit.models import AuditEvent
from apps.contributions.enums import ContributionSource, EvidenceScanStatus, VerificationStatus
from apps.contributions.models import safe_evidence_filename
from apps.contributions.services import (
    Evidence,
    EvidenceFilePendingScanError,
    InvalidEvidenceError,
    InvalidEvidenceFileError,
    record_evidence_scan_result,
    submit_evidence,
    verify,
)
from apps.contributions.tests.factories import contribution_type
from apps.projects.enums import ContributionMode, ProjectStatus
from apps.projects.tests.factories import ProjectFactory, ProjectMaintainerFactory, UserFactory
from apps.taxonomy.enums import TermVocabulary
from apps.taxonomy.tests.factories import TaxonomyTermFactory

pytestmark = [pytest.mark.django_db]


@pytest.fixture(autouse=True)
def isolated_evidence_storage(settings, tmp_path):
    """SEC-007: upload tests never leave evidence files in the source tree."""
    settings.MEDIA_ROOT = tmp_path


@pytest.mark.unit
def test_submitted_evidence_is_candidate_not_verification():
    """BR-006: self-submission alone is evidence; the record starts unverified."""
    member = UserFactory()
    project = ProjectFactory(
        status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
        contribution_mode=ContributionMode.OPEN_DIRECT,
    )

    record = submit_evidence(
        member,
        project,
        Evidence(
            title="Nepali dashboard translation sprint",
            contribution_type=contribution_type("localization"),
            description="Translated 40 strings for the citizen dashboard.",
            evidence_url="https://github.com/moit/service-directory/pull/12",
        ),
    )

    assert record.contributor == member
    assert record.project == project
    assert record.source == ContributionSource.MEMBER_SUBMISSION
    assert record.status == VerificationStatus.CANDIDATE
    assert record.verified_by is None
    assert record.verified_at is None
    assert record.contribution_type.slug == "localization"


@pytest.mark.unit
def test_evidence_requires_an_approved_contribution_category():
    """GOV-008/A6: evidence must target an active CONTRIBUTION_TYPE term."""
    member = UserFactory()
    project = ProjectFactory()
    wrong_vocabulary = TaxonomyTermFactory(vocabulary=TermVocabulary.TECHNOLOGY)
    inactive = TaxonomyTermFactory(
        vocabulary=TermVocabulary.CONTRIBUTION_TYPE, label="Legacy", slug="legacy", is_active=False
    )

    with pytest.raises(InvalidEvidenceError):
        submit_evidence(member, project, Evidence(title="X", contribution_type=wrong_vocabulary))
    with pytest.raises(InvalidEvidenceError):
        submit_evidence(member, project, Evidence(title="X", contribution_type=inactive))


@pytest.mark.unit
def test_evidence_requires_title_and_active_member():
    """BR-006: incomplete evidence is refused at the service boundary."""
    project = ProjectFactory()

    with pytest.raises(InvalidEvidenceError):
        submit_evidence(
            UserFactory(), project, Evidence(title="   ", contribution_type=contribution_type("qa"))
        )
    inactive = UserFactory(is_active=False)
    with pytest.raises(InvalidEvidenceError):
        submit_evidence(
            inactive, project, Evidence(title="Title", contribution_type=contribution_type("qa"))
        )
    assert project.contributions.count() == 0


@pytest.mark.unit
def test_link_only_evidence_does_not_claim_a_pending_file_scan():
    """SEC-007: a record without an attachment has no fictitious scan pending."""
    member = UserFactory()
    project = ProjectFactory(
        status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
        contribution_mode=ContributionMode.OPEN_DIRECT,
    )

    record = submit_evidence(
        member,
        project,
        Evidence(
            title="Public pull request",
            contribution_type=contribution_type("qa"),
            evidence_url="https://example.gov.np/evidence/1",
        ),
    )

    assert record.evidence_scan == EvidenceScanStatus.NOT_APPLICABLE


@pytest.mark.unit
@pytest.mark.parametrize(
    ("unsafe_name", "expected_name"),
    [
        ("../../review.pdf", "review.pdf"),
        (r"..\\review..pdf", "review.pdf"),
        ("...", "evidence"),
    ],
)
def test_sec007_evidence_storage_names_are_path_safe(unsafe_name, expected_name):
    """SEC-007/SEC-004: stored evidence names discard path traversal and dot-segment input."""
    assert safe_evidence_filename(unsafe_name) == expected_name


@pytest.mark.integration
def test_sec007_file_evidence_is_content_checked_renamed_and_pending_scan():
    """SEC-007: a valid PDF is content-checked, safely stored, and unavailable until scanning."""
    member = UserFactory()
    project = ProjectFactory(
        status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
        contribution_mode=ContributionMode.OPEN_DIRECT,
    )
    evidence_file = SimpleUploadedFile(
        "../../review.pdf", b"%PDF-1.7 evidence", content_type="application/octet-stream"
    )

    record = submit_evidence(
        member,
        project,
        Evidence(
            title="Accessibility review",
            contribution_type=contribution_type("qa"),
            evidence_file=evidence_file,
        ),
    )

    assert record.evidence_scan == EvidenceScanStatus.PENDING
    assert record.evidence_content_type == "application/pdf"
    assert record.evidence_size_bytes == len(b"%PDF-1.7 evidence")
    assert ".." not in record.evidence_file.name
    assert record.evidence_file.name.startswith("contribution-evidence/")


@pytest.mark.integration
@pytest.mark.parametrize(
    ("filename", "payload"),
    [
        ("installer.exe", b"MZ executable"),
        ("evidence.pdf", b"MZ executable disguised as PDF"),
        ("evidence.svg", b"<svg onload=alert(1) />"),
        ("evidence.pdf", b"not actually a PDF"),
    ],
)
def test_sec007_file_evidence_rejects_executables_disallowed_extensions_and_signature_mismatch(
    filename, payload
):
    """SEC-007: client MIME cannot bypass extension, executable-signature, or content checks."""
    member = UserFactory()
    project = ProjectFactory(
        status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
        contribution_mode=ContributionMode.OPEN_DIRECT,
    )

    with pytest.raises(InvalidEvidenceFileError):
        submit_evidence(
            member,
            project,
            Evidence(
                title="Unsafe file",
                contribution_type=contribution_type("qa"),
                evidence_file=SimpleUploadedFile(filename, payload, content_type="application/pdf"),
            ),
        )

    assert project.contributions.count() == 0


@pytest.mark.integration
def test_sec007_file_evidence_enforces_max_attachment_bytes_and_quarantines_failed_scan(
    monkeypatch,
):
    """SEC-007: oversized files fail closed and failed scans purge quarantined files."""
    member = UserFactory()
    project = ProjectFactory(
        status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
        contribution_mode=ContributionMode.OPEN_DIRECT,
    )
    monkeypatch.setattr("apps.contributions.services.max_evidence_file_bytes", lambda: 8)
    with pytest.raises(InvalidEvidenceFileError):
        submit_evidence(
            member,
            project,
            Evidence(
                title="Oversized file",
                contribution_type=contribution_type("qa"),
                evidence_file=SimpleUploadedFile("large.pdf", b"%PDF-1.7 oversized"),
            ),
        )

    monkeypatch.setattr("apps.contributions.services.max_evidence_file_bytes", lambda: 1024)
    record = submit_evidence(
        member,
        project,
        Evidence(
            title="Scanned file",
            contribution_type=contribution_type("qa"),
            evidence_file=SimpleUploadedFile("scanned.pdf", b"%PDF-1.7 reviewed"),
        ),
    )
    record_evidence_scan_result(record, EvidenceScanStatus.FAILED)
    record.refresh_from_db()

    assert record.evidence_scan == EvidenceScanStatus.QUARANTINED
    assert not record.evidence_file
    assert AuditEvent.objects.filter(
        action="contribution.evidence_scanned",
        object_id=str(record.pk),
        after={"evidence_scan": EvidenceScanStatus.QUARANTINED},
    ).exists()


@pytest.mark.integration
def test_sec007_file_backed_evidence_cannot_be_accepted_before_a_clean_external_result():
    """SEC-007/BR-006: pending or quarantined file evidence cannot earn verified credit."""
    member = UserFactory()
    project = ProjectFactory(
        status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
        contribution_mode=ContributionMode.OPEN_DIRECT,
    )
    record = submit_evidence(
        member,
        project,
        Evidence(
            title="Accessibility review",
            contribution_type=contribution_type("qa"),
            evidence_file=SimpleUploadedFile("review.pdf", b"%PDF-1.7 evidence"),
        ),
    )
    maintainer = ProjectMaintainerFactory(project=project).user

    with pytest.raises(EvidenceFilePendingScanError):
        verify(maintainer, record, VerificationStatus.ACCEPTED, "Review is complete")

    record_evidence_scan_result(record, EvidenceScanStatus.CLEAN)
    verified = verify(maintainer, record, VerificationStatus.ACCEPTED, "Review is complete")

    assert verified.status == VerificationStatus.ACCEPTED
