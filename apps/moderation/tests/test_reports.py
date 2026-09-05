import json
import unicodedata

import pytest

from apps.ministries.tests.factories import UserFactory
from apps.moderation.enums import CaseEventType, CaseStatus, ReportReason
from apps.moderation.models import ModerationCase, Report
from apps.moderation.services import file_report, public_summary
from apps.moderation.tests.factories import ModerationCaseFactory, ReportFactory
from apps.projects.tests.factories import ProjectFactory, ProjectLinkFactory

pytestmark = [pytest.mark.django_db]

SECURITY_REASONS = (
    ReportReason.SECURITY_CONCERN,
    ReportReason.MALWARE,
    ReportReason.UNSAFE_LINK,
)

ROUTINE_REASONS = (
    ReportReason.SPAM,
    ReportReason.HARASSMENT,
    ReportReason.COPYRIGHT,
    ReportReason.IMPERSONATION,
    ReportReason.GOV_BRANDING_MISUSE,
    ReportReason.UNLAWFUL_CONTENT,
    ReportReason.OTHER,
)


@pytest.mark.unit
def test_file_report_accepts_structured_reasons_only():
    """ADM-003: reports use structured reasons; anything else is a typed error, nothing stored."""
    reporter = UserFactory()
    target = ProjectFactory()
    with pytest.raises(Exception) as excinfo:
        file_report(reporter, target, "it looks bad")
    assert type(excinfo.value).__name__ == "InvalidReportReason"
    assert Report.objects.count() == 0
    assert ModerationCase.objects.count() == 0

    report = file_report(
        reporter, target, ReportReason.SPAM, details="repeated advertising comments"
    )
    assert report.reason == ReportReason.SPAM
    assert report.target == target
    assert report.case.status == CaseStatus.NEW
    assert report.case.events.filter(event=CaseEventType.CREATED).exists()


@pytest.mark.integration
@pytest.mark.parametrize("reason", SECURITY_REASONS)
def test_security_reports_route_to_security_queue(reason):
    """ADM-003: security concerns are filed straight into the ESCALATED security queue."""
    report = file_report(UserFactory(), ProjectFactory(), reason)
    assert report.case.status == CaseStatus.ESCALATED


@pytest.mark.integration
@pytest.mark.parametrize("reason", ROUTINE_REASONS)
def test_routine_reports_open_new_cases(reason):
    """ADM-003: non-security reports enter the routine NEW queue, separated from security."""
    report = file_report(UserFactory(), ProjectFactory(), reason)
    assert report.case.status == CaseStatus.NEW


@pytest.mark.unit
def test_file_report_allows_anonymous_reporter():
    """ADM-003: system/automated reports carry a null reporter."""
    report = file_report(None, ProjectFactory(), ReportReason.MALWARE)
    report.refresh_from_db()
    assert report.reporter is None
    assert report.case.status == CaseStatus.ESCALATED


@pytest.mark.integration
@pytest.mark.parametrize("target_factory", [ProjectFactory, UserFactory, ProjectLinkFactory])
def test_report_reaches_queue_from_any_content_type(target_factory):
    """A7/ADM-003: profile, project, and link targets are reportable via the generic FK."""
    target = target_factory()
    report = file_report(UserFactory(), target, ReportReason.UNSAFE_LINK)
    assert report.target == target
    assert report.content_type.model == target._meta.model_name
    assert report.case is not None


@pytest.mark.integration
def test_unsafe_link_report_reaches_security_queue():
    """ADM-003: an unsafe-link report lands in the security queue, not routine review."""
    link = ProjectLinkFactory()
    report = file_report(UserFactory(), link, ReportReason.UNSAFE_LINK, evidence_url=link.url)
    assert report.case.status == CaseStatus.ESCALATED


@pytest.mark.integration
def test_public_summary_redacts_reporter_and_evidence():
    """ADM-003/SRS 13.2: public case summaries never expose the reporter identity or evidence."""
    reporter = UserFactory(username="leaky-reporter")
    report = ReportFactory(
        reporter=reporter,
        details="reporter saw the attacker's private messages",
        evidence_url="https://private-evidence.example/leak",
    )
    case = ModerationCaseFactory(report=report, status=CaseStatus.ACTION_TAKEN)

    summary = public_summary(case)

    assert "reporter" not in summary
    dumped = json.dumps(summary)
    assert reporter.username not in dumped
    assert "evidence" not in dumped
    assert report.evidence_url not in dumped
    assert report.details not in dumped


@pytest.mark.unit
def test_report_details_normalized_to_nfc():
    """DSC-003: report details are NFC-normalized and trimmed on save (D15 round-trip identity)."""
    text = "प्रविधि समीक्षा टिप्पणी"
    report = ReportFactory(details=f"  {unicodedata.normalize('NFD', text)}  ")
    report.refresh_from_db()
    assert report.details == unicodedata.normalize("NFC", text)
