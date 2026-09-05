import json

import pytest
from django.db.models import Q

from apps.audit.models import AuditEvent
from apps.ministries.tests.factories import SuperAdminFactory, UserFactory
from apps.moderation.enums import CaseStatus, ModerationAction, ReportReason
from apps.moderation.models import ModerationCase
from apps.moderation.services import export_cases, record_decision
from apps.moderation.tests.factories import ModerationCaseFactory

pytestmark = [pytest.mark.django_db]


def secret_cases(count: int) -> list[ModerationCase]:
    cases = []
    for _ in range(count):
        case = ModerationCaseFactory(status=CaseStatus.UNDER_REVIEW)
        case.report.details = "SECRET-REPORT-DETAILS"
        case.report.save(update_fields=["details"])
        record_decision(
            SuperAdminFactory(),
            case,
            ModerationAction.WARNING,
            ReportReason.SPAM,
            comment="SECRET-DECISION-COMMENT",
        )
        cases.append(case)
    return cases


@pytest.mark.integration
def test_export_requires_super_admin_and_is_denial_audited():
    """ADM-005: privileged export is access-controlled; denials are audited."""
    ModerationCaseFactory()
    impostor = UserFactory()

    with pytest.raises(Exception) as excinfo:
        export_cases(impostor, ModerationCase.objects.all(), "annual oversight report")
    assert type(excinfo.value).__name__ == "ModerationAuthorizationError"
    assert AuditEvent.objects.filter(
        action="moderation.case.export.denied", actor=impostor, result="failure"
    ).exists()


@pytest.mark.integration
def test_export_requires_declared_purpose():
    """ADM-005: export without a purpose-limited justification is rejected and audited."""
    ModerationCaseFactory()
    super_admin = SuperAdminFactory()

    with pytest.raises(Exception) as excinfo:
        export_cases(super_admin, ModerationCase.objects.all(), "  ")
    assert type(excinfo.value).__name__ == "ExportPurposeError"
    assert AuditEvent.objects.filter(
        action="moderation.case.export.denied", actor=super_admin, result="failure"
    ).exists()


@pytest.mark.integration
def test_export_is_audited_with_count_and_filters_never_contents():
    """ADM-005: export logs purpose, count, and filter fields — never case contents."""
    secret_cases(3)
    ModerationCaseFactory(status=CaseStatus.NEW)
    super_admin = SuperAdminFactory()
    queryset = ModerationCase.objects.filter(status=CaseStatus.ACTION_TAKEN).filter(
        Q(action_reason=ReportReason.SPAM)
    )

    exported = export_cases(super_admin, queryset, "quarterly oversight review")

    assert len(exported) == 3
    audit = AuditEvent.objects.get(action="moderation.case.export", actor=super_admin)
    assert audit.after["purpose"] == "quarterly oversight review"
    assert audit.after["count"] == 3
    assert sorted(audit.after["filters"]) == ["action_reason", "status"]
    dumped = json.dumps({"before": audit.before, "after": audit.after})
    assert "SECRET-DECISION-COMMENT" not in dumped
    assert "SECRET-REPORT-DETAILS" not in dumped
