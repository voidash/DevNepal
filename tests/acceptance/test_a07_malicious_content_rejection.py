"""A7 — Malicious blog payload and unsafe file/link rejected or sanitized; the
moderation report reaches the correct queue without exposing evidence publicly.

Covers docs/test-plan.md A7 rows 1-4 against the existing service surfaces:
apps.blogs create_listing (D13 link-listings, BLG-004, BR-009), apps.projects
attachment services (GOV-003, SEC-007), apps.accounts NormalizedURLField
(MEM-007), and apps/moderation services (ADM-002, ADM-003, SRS 13.2).
"""

import json

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from apps.accounts.enums import LinkType
from apps.accounts.models import MemberLink
from apps.audit.models import AuditEvent
from apps.blogs.enums import BlogModerationState, BlogStatus
from apps.blogs.models import BlogPost
from apps.blogs.services import (
    BlogCanonicalUrlError,
    create_listing,
    create_native_post,
    flag_post,
    publish_listing,
    restrict_post,
)
from apps.blogs.tests.factories import BlogPostFactory, UserFactory
from apps.ministries.tests.factories import SuperAdminFactory
from apps.moderation.enums import CaseStatus, ModerationAction, ReportReason
from apps.moderation.services import assign_case, file_report, public_summary, record_decision
from apps.projects.enums import ScanStatus
from apps.projects.services import (
    AttachmentError,
    add_attachment,
    check_publish_readiness,
    record_scan_result,
)
from apps.projects.tests.factories import make_publishable

pytestmark = [pytest.mark.django_db, pytest.mark.acceptance]

SCRIPT_PAYLOADS = [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "<iframe src='https://evil.example'></iframe>",
]

RENDERED_CONTENT_FIELDS = {
    "content_markdown",
    "content_rendered",
    "content_html",
    "rendered_html",
    "body_html",
}


# ---------------------------------------------------------------------------
# 1. Blog payload attacks (BLG-003 partial, BLG-004, SEC-004, A7)


@pytest.mark.parametrize("field", ["title", "excerpt"])
@pytest.mark.parametrize("payload", SCRIPT_PAYLOADS)
def test_a07_script_payload_in_listing_is_rejected_or_stored_inert(field, payload):
    """A7/BLG-003/SEC-004/D13: external-listing payloads never reach rendered content.

    External listings store only metadata. Native articles have a separate,
    sanitized rendering path and do not weaken the external-listing boundary.
    """
    member = UserFactory()
    kwargs = {
        "title": "Benign listing title" if field != "title" else payload,
        "excerpt": "Benign excerpt." if field != "excerpt" else payload,
        "canonical_url": "https://medium.com/@writer/nepali-nlp-pipelines",
    }

    try:
        post = create_listing(member, **kwargs)
    except BlogCanonicalUrlError:
        post = None
    except Exception as exc:
        raise AssertionError(f"payload rejected with an unexpected error type: {exc!r}") from exc

    stored_fields = {f.name for f in BlogPost._meta.get_fields()}
    assert {"content_markdown", "content_rendered"} <= stored_fields

    if post is not None:
        post.refresh_from_db()
        assert getattr(post, field) == payload
        assert post.content_markdown == ""
        assert post.content_rendered == ""
        snapshot = post.versions.order_by("-version_number").first().snapshot
        assert snapshot[field] == payload


def test_a07_native_blog_payload_is_rendered_inert():
    """A7/BLG-002/BLG-003/SEC-004: native raw HTML is escaped before publication."""
    post = create_native_post(
        UserFactory(),
        title="Native security note",
        content_markdown="# Finding\n\n<script>alert(1)</script>",
    )

    assert "<h1>Finding</h1>" in post.content_rendered
    assert "<script>" not in post.content_rendered
    assert "&lt;script&gt;" in post.content_rendered


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "javascript:alert(1)",
        "JaVaScRiPt:alert(document.cookie)",
        "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
        "vbscript:msgbox(1)",
    ],
)
def test_a07_unsafe_scheme_canonical_url_rejected(unsafe_url):
    """A7/BLG-004/SEC-004: javascript:/data:/vbscript: canonical URLs are rejected."""
    member = UserFactory()
    with pytest.raises(BlogCanonicalUrlError):
        create_listing(member, title="Scheme attack", canonical_url=unsafe_url)
    assert not BlogPost.objects.filter(author=member).exists()


@pytest.mark.parametrize(
    ("raw_url", "normalized_url"),
    [
        ("HTTPS://Medium.COM/@writer/nepali-nlp", "https://medium.com/@writer/nepali-nlp"),
        ("https://EXAMPLE.com./posts/1", "https://example.com./posts/1"),
    ],
)
def test_a07_canonical_url_scheme_and_host_normalized(raw_url, normalized_url):
    """A7/BLG-004/MEM-007: scheme and host are lowercased before the http/https allowlist,
    so mixed-case hosts and trailing-dot FQDN spellings collapse to one canonical form."""
    post = create_listing(UserFactory(), title="Normalization", canonical_url=raw_url)
    post.refresh_from_db()
    assert post.canonical_url == normalized_url


# ---------------------------------------------------------------------------
# 2. Unsafe file/link (SEC-007, GOV-003, MEM-007)


def test_a07_oversized_attachment_rejected():
    """A7/SEC-007/GOV-003: an upload larger than MAX_ATTACHMENT_BYTES is rejected outright."""
    project = make_publishable()
    oversized = SimpleUploadedFile("huge.pdf", b"x" * 64, content_type="application/pdf")
    with override_settings(MAX_ATTACHMENT_BYTES=8):
        with pytest.raises(AttachmentError):
            add_attachment(project.owner, project, kind="proposal", file=oversized)
    assert not project.attachments.exists()


@pytest.mark.parametrize("filename", ["installer.exe", "run.sh", "logo.svg"])
def test_a07_executable_and_active_content_attachments_rejected(filename):
    """A7/SEC-007: executable and scriptable extensions are refused before storage."""
    project = make_publishable()
    hostile = SimpleUploadedFile(filename, b"payload", content_type="application/octet-stream")
    with pytest.raises(AttachmentError):
        add_attachment(project.owner, project, kind="other", file=hostile)
    assert not project.attachments.exists()


def test_a07_failed_scan_quarantines_file_and_blocks_publication():
    """A7/SEC-007/GOV-003: a failed malware scan quarantines, purges the file, and the
    project cannot pass the publication readiness gate."""
    project = make_publishable()
    attachment = add_attachment(
        project.owner,
        project,
        kind="proposal",
        file=SimpleUploadedFile("proposal.pdf", b"%PDF-1.4 doc", content_type="application/pdf"),
    )

    record_scan_result(attachment, ScanStatus.FAILED)
    attachment.refresh_from_db()
    assert attachment.scan == ScanStatus.QUARANTINED
    assert not attachment.file
    assert "attachment_quarantined" in check_publish_readiness(project)


def test_a07_content_type_mismatch_attachment_rejected():
    """A7/SEC-007: a PDF-named upload whose bytes are a PE executable must be rejected
    or quarantined at upload time (validate file type by content)."""
    project = make_publishable()
    trojan = SimpleUploadedFile(
        "invoice.pdf", b"MZ\x90\x00\x03\x00trojan-payload", content_type="application/pdf"
    )
    with pytest.raises(AttachmentError):
        add_attachment(project.owner, project, kind="other", file=trojan)
    assert not project.attachments.filter(original_filename="invoice.pdf").exists()


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "javascript:alert(1)",
        "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
    ],
)
def test_a07_unsafe_scheme_member_profile_link_rejected(unsafe_url):
    """A7/MEM-007/SEC-004: javascript:/data: links are rejected by the member-profile
    URL field contract (http/https only at clean time)."""
    link = MemberLink(user=UserFactory(), link_type=LinkType.PORTFOLIO, url=unsafe_url)
    with pytest.raises(ValidationError) as excinfo:
        link.full_clean()
    assert "url" in excinfo.value.error_dict


# ---------------------------------------------------------------------------
# 3. Moderation queue routing and evidence confidentiality (ADM-002, ADM-003, SRS 13.2)


@pytest.mark.parametrize(
    "security_reason",
    [ReportReason.UNSAFE_LINK, ReportReason.MALWARE, ReportReason.SECURITY_CONCERN],
)
def test_a07_security_report_routed_to_escalated_queue(security_reason):
    """A7/ADM-003/SRS 13.2: a malicious blog/link report files directly into the
    ESCALATED security queue, separated from routine review."""
    report = file_report(UserFactory(), BlogPostFactory(), security_reason)
    case = report.case
    assert case.status == CaseStatus.ESCALATED
    assert case.events.filter(event="created").exists()


def test_a07_routine_report_routed_to_standard_queue():
    """A7/ADM-002/ADM-003: non-security reports open in the standard NEW queue."""
    report = file_report(UserFactory(), BlogPostFactory(), ReportReason.SPAM)
    assert report.case.status == CaseStatus.NEW


def test_a07_public_summary_hides_reporter_and_evidence():
    """A7/ADM-003/SRS 13.2, 9.2: the public case summary exposes queue state only —
    never the reporter, the report details, or the evidence URL."""
    reporter = UserFactory()
    details = "Reporter privately observed credential dump marker saxena-secret-7"
    evidence_url = "https://evil.example/evidence/creds.txt"
    report = file_report(
        reporter,
        BlogPostFactory(),
        ReportReason.UNSAFE_LINK,
        details=details,
        evidence_url=evidence_url,
    )

    summary = public_summary(report.case)
    assert set(summary) == {"id", "status", "reason", "target_model", "action", "created_at"}
    serialized = json.dumps(summary)
    assert reporter.username not in serialized
    assert "saxena-secret-7" not in serialized
    assert evidence_url not in serialized


# ---------------------------------------------------------------------------
# 4. End-to-end A7 narrative (A7, BLG-006, ADM-004, SEC-008)


def test_a07_attack_report_unpublish_decision_and_audit_chain():
    """BLG-006/ADM-004/SEC-008: payload listing stays inert → community report flags it → the case
    escalates to the security queue → a Super Admin decides unpublish → the post is
    restricted from public view → every step leaves an immutable audit row."""
    attacker = UserFactory()
    reporter = UserFactory()
    admin = SuperAdminFactory()

    post = create_listing(
        attacker,
        title="<script>alert('gov-portal')</script>",
        excerpt="<iframe src='https://evil.example'></iframe>",
        canonical_url="https://medium.com/@attacker/stolen-credentials-guide",
    )
    publish_listing(attacker, post)
    post.refresh_from_db()
    assert post.status == BlogStatus.PUBLISHED
    assert post.content_markdown == ""
    assert post.content_rendered == ""

    flag_post(reporter, post)
    post.refresh_from_db()
    assert post.moderation_state == BlogModerationState.UNDER_REVIEW

    report = file_report(
        reporter,
        post,
        ReportReason.UNSAFE_LINK,
        details="Link leads to a credential-harvesting clone",
        evidence_url="https://evil.example/harvest",
    )
    case = report.case
    assert case.status == CaseStatus.ESCALATED

    assign_case(admin, case)
    assert case.status == CaseStatus.UNDER_REVIEW

    decided = record_decision(
        admin, case, ModerationAction.UNPUBLISH, ReportReason.UNSAFE_LINK, comment="Malicious link"
    )
    assert decided.status == CaseStatus.ACTION_TAKEN
    assert decided.action == ModerationAction.UNPUBLISH
    assert decided.action_reason == ReportReason.UNSAFE_LINK

    restrict_post(admin, post)
    post.refresh_from_db()
    assert post.moderation_state == BlogModerationState.RESTRICTED

    blog_actions = set(
        AuditEvent.objects.filter(
            content_type__app_label="blogs", object_id=str(post.pk)
        ).values_list("action", flat=True)
    )
    assert {
        "blog.created",
        "blog.published",
        "blog.moderation.flagged",
        "blog.moderation.restricted",
    } <= blog_actions
    case_actions = set(
        AuditEvent.objects.filter(
            content_type__app_label="moderation", object_id=str(case.pk)
        ).values_list("action", flat=True)
    )
    assert {"moderation.case.assign", "moderation.case.decide"} <= case_actions

    serialized = json.dumps(public_summary(case))
    assert reporter.username not in serialized
    assert "https://evil.example/harvest" not in serialized
