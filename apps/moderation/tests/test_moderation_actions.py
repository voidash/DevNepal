import json

import pytest

from apps.audit.models import AuditEvent
from apps.blogs.enums import BlogModerationState
from apps.blogs.tests.factories import BlogPostFactory
from apps.ministries.tests.factories import SuperAdminFactory, UserFactory
from apps.moderation.enums import (
    CaseEventType,
    CaseStatus,
    ModerationAction,
    ReportReason,
)
from apps.moderation.models import ModerationCase, ModerationEvent, Report
from apps.moderation.services import (
    assign_case,
    enable_security_containment,
    record_decision,
)
from apps.moderation.tests.factories import ModerationCaseFactory, ModerationEventFactory
from apps.projects.enums import ProjectStatus
from apps.projects.tests.factories import ProjectFactory

pytestmark = [pytest.mark.django_db]

ALL_ACTIONS = tuple(ModerationAction.values)

ACTION_TARGET_STATUS = {
    ModerationAction.NO_ACTION: CaseStatus.CLOSED_NO_ACTION,
    ModerationAction.WARNING: CaseStatus.ACTION_TAKEN,
    ModerationAction.CONTENT_RESTRICTION: CaseStatus.ACTION_TAKEN,
    ModerationAction.UNPUBLISH: CaseStatus.ACTION_TAKEN,
    ModerationAction.ACCOUNT_SUSPENSION: CaseStatus.ACTION_TAKEN,
    ModerationAction.ESCALATION: CaseStatus.ESCALATED,
}


@pytest.mark.integration
@pytest.mark.parametrize("action", ALL_ACTIONS)
def test_every_action_requires_structured_reason_and_writes_audit(action):
    """ADM-004: each graduated action records a structured reason, event, and audit entry."""
    super_admin = SuperAdminFactory()
    if action == ModerationAction.ACCOUNT_SUSPENSION:
        report = Report.objects.create(
            reporter=UserFactory(), target=UserFactory(), reason=ReportReason.SPAM
        )
        case = ModerationCase.objects.create(report=report, status=CaseStatus.UNDER_REVIEW)
    else:
        case = ModerationCaseFactory(status=CaseStatus.UNDER_REVIEW)

    record_decision(super_admin, case, action, ReportReason.SPAM, comment="repeat abuse")

    case.refresh_from_db()
    assert case.action == action
    assert case.action_reason == ReportReason.SPAM
    assert case.decided_by == super_admin
    assert case.decided_at is not None
    assert case.status == ACTION_TARGET_STATUS[action]
    expected_event = (
        CaseEventType.ESCALATED
        if action == ModerationAction.ESCALATION
        else CaseEventType.ACTION_TAKEN
    )
    assert case.events.filter(event=expected_event).exists()
    audit = AuditEvent.objects.get(action="moderation.case.decide", object_id=str(case.pk))
    assert audit.actor == super_admin
    assert audit.before["status"] == CaseStatus.UNDER_REVIEW
    assert audit.after["action"] == action
    assert audit.after["action_reason"] == ReportReason.SPAM


@pytest.mark.integration
@pytest.mark.parametrize(
    "action", [ModerationAction.UNPUBLISH, ModerationAction.ACCOUNT_SUSPENSION]
)
@pytest.mark.parametrize("bad_reason", ["", "   ", "because i said so", None])
def test_enforcement_without_defined_reason_is_rejected(action, bad_reason):
    """BR-010: takedown/suspension without a defined reason is rejected with nothing recorded."""
    super_admin = SuperAdminFactory()
    case = ModerationCaseFactory(status=CaseStatus.UNDER_REVIEW)

    with pytest.raises(Exception) as excinfo:
        record_decision(super_admin, case, action, bad_reason)
    assert type(excinfo.value).__name__ == "ModerationDecisionError"

    case.refresh_from_db()
    assert case.action == ""
    assert case.decided_at is None
    assert case.status == CaseStatus.UNDER_REVIEW
    assert not case.events.filter(event=CaseEventType.ACTION_TAKEN).exists()
    assert not AuditEvent.objects.filter(action="moderation.case.decide").exists()
    assert AuditEvent.objects.filter(action="moderation.case.decide.denied").exists()


@pytest.mark.integration
def test_unknown_action_is_rejected():
    """ADM-004: only the six graduated actions are valid decisions."""
    with pytest.raises(Exception) as excinfo:
        record_decision(
            SuperAdminFactory(), ModerationCaseFactory(), "shadowban", ReportReason.SPAM
        )
    assert type(excinfo.value).__name__ == "ModerationDecisionError"


@pytest.mark.integration
def test_decision_requires_super_admin_and_denial_is_audited():
    """ADM-004/§4.2: only Super Admins decide cases; denials are audited failures."""
    impostor = UserFactory(is_staff=True)
    case = ModerationCaseFactory(status=CaseStatus.UNDER_REVIEW)

    with pytest.raises(Exception) as excinfo:
        record_decision(impostor, case, ModerationAction.WARNING, ReportReason.SPAM)
    assert type(excinfo.value).__name__ == "ModerationAuthorizationError"

    case.refresh_from_db()
    assert case.decided_by is None
    assert AuditEvent.objects.filter(
        action="moderation.case.decide.denied", actor=impostor, result="failure"
    ).exists()


@pytest.mark.integration
def test_decision_denied_without_otp_verified_super_admin():
    """AUTH-005/ADM-004/SEC-008: unverified Super Admin moderation is denied and audited."""
    super_admin = SuperAdminFactory()
    super_admin.otp_device = None
    super_admin.is_verified = lambda: False
    case = ModerationCaseFactory(status=CaseStatus.UNDER_REVIEW)

    with pytest.raises(Exception) as excinfo:
        record_decision(super_admin, case, ModerationAction.WARNING, ReportReason.SPAM)

    assert type(excinfo.value).__name__ == "ModerationAuthorizationError"
    case.refresh_from_db()
    assert case.decided_by is None
    assert AuditEvent.objects.filter(
        actor=super_admin, action="moderation.case.decide.denied", result="failure"
    ).exists()


@pytest.mark.integration
def test_escalation_decision_lands_in_security_queue():
    """ADM-004: escalation moves the case into the ESCALATED security queue."""
    case = ModerationCaseFactory(status=CaseStatus.UNDER_REVIEW)
    record_decision(
        SuperAdminFactory(), case, ModerationAction.ESCALATION, ReportReason.SECURITY_CONCERN
    )
    case.refresh_from_db()
    assert case.status == CaseStatus.ESCALATED
    assert case.events.filter(event=CaseEventType.ESCALATED).exists()


@pytest.mark.integration
def test_assign_case_moves_to_under_review_with_event_and_audit():
    """ADM-002: assignment is recorded on the timeline and audited."""
    super_admin = SuperAdminFactory()
    case = ModerationCaseFactory(status=CaseStatus.NEW)

    assign_case(super_admin, case)

    case.refresh_from_db()
    assert case.assigned_to == super_admin
    assert case.status == CaseStatus.UNDER_REVIEW
    assert case.events.filter(event=CaseEventType.ASSIGNED, actor=super_admin).exists()
    assert AuditEvent.objects.filter(
        action="moderation.case.assign", object_id=str(case.pk)
    ).exists()


@pytest.mark.integration
def test_urgent_security_containment_requires_reason_and_is_audited():
    """BR-010: urgent security containment is a flagged exception with an audited reason."""
    super_admin = SuperAdminFactory()
    case = ModerationCaseFactory(status=CaseStatus.ESCALATED)

    with pytest.raises(Exception) as excinfo:
        enable_security_containment(super_admin, case, "  ")
    assert type(excinfo.value).__name__ == "ModerationDecisionError"
    case.refresh_from_db()
    assert case.security_containment is False
    assert AuditEvent.objects.filter(
        action="moderation.case.contain.denied", result="failure"
    ).exists()

    enable_security_containment(super_admin, case, "active malware distribution")
    case.refresh_from_db()
    assert case.security_containment is True
    assert case.events.filter(event=CaseEventType.ESCALATED).exists()
    audit = AuditEvent.objects.get(action="moderation.case.contain", object_id=str(case.pk))
    assert audit.after["reason"] == "active malware distribution"


@pytest.mark.integration
def test_containment_audit_payload_stays_purpose_limited():
    """SEC-008: containment audit records the flag and reason, never case evidence."""
    case = ModerationCaseFactory()
    case.report.details = "confidential whistle-blower details"
    case.report.save(update_fields=["details"])

    enable_security_containment(SuperAdminFactory(), case, "containment rationale")

    audit = AuditEvent.objects.get(action="moderation.case.contain")
    dumped = json.dumps({"before": audit.before, "after": audit.after})
    assert "whistle-blower" not in dumped
    assert "details" not in dumped


@pytest.mark.unit
def test_moderation_events_are_append_only():
    """SEC-008/ADM-008: the case timeline can never be rewritten or deleted."""
    event = ModerationEventFactory()
    event.comment = "rewritten history"
    with pytest.raises(PermissionError):
        event.save()
    with pytest.raises(PermissionError):
        event.delete()
    stored = ModerationEvent.objects.get(pk=event.pk)
    assert stored.comment == ""


@pytest.mark.integration
def test_unpublish_decision_removes_a_reported_project_from_public_listing():
    """ADM-004/BR-010: unpublish decisions enforce removal of a reported project."""
    project = ProjectFactory(status=ProjectStatus.OPEN_FOR_CONTRIBUTION)
    report = Report.objects.create(reporter=UserFactory(), target=project, reason=ReportReason.SPAM)
    case = ModerationCase.objects.create(report=report, status=CaseStatus.UNDER_REVIEW)

    record_decision(SuperAdminFactory(), case, ModerationAction.UNPUBLISH, ReportReason.SPAM)

    project.refresh_from_db()
    assert project.status == ProjectStatus.DRAFT


@pytest.mark.integration
def test_content_restriction_decision_restricts_a_reported_blog_listing():
    """ADM-004/BLG-006: a content restriction changes the reported blog's public state."""
    post = BlogPostFactory(moderation_state=BlogModerationState.UNDER_REVIEW)
    report = Report.objects.create(reporter=UserFactory(), target=post, reason=ReportReason.SPAM)
    case = ModerationCase.objects.create(report=report, status=CaseStatus.UNDER_REVIEW)

    record_decision(
        SuperAdminFactory(), case, ModerationAction.CONTENT_RESTRICTION, ReportReason.SPAM
    )

    post.refresh_from_db()
    assert post.moderation_state == BlogModerationState.RESTRICTED


@pytest.mark.integration
def test_account_suspension_decision_deactivates_a_reported_member():
    """ADM-004/AUTH-009: account suspension makes the reported member unable to authenticate."""
    member = UserFactory(is_active=True)
    report = Report.objects.create(
        reporter=UserFactory(), target=member, reason=ReportReason.HARASSMENT
    )
    case = ModerationCase.objects.create(report=report, status=CaseStatus.UNDER_REVIEW)

    record_decision(
        SuperAdminFactory(), case, ModerationAction.ACCOUNT_SUSPENSION, ReportReason.HARASSMENT
    )

    member.refresh_from_db()
    assert member.is_active is False
