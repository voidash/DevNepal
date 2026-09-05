import pytest

from apps.audit.models import AuditEvent
from apps.blogs.enums import BlogModerationState
from apps.blogs.tests.factories import BlogPostFactory
from apps.ministries.tests.factories import SuperAdminFactory, UserFactory
from apps.moderation.enums import (
    AppealStatus,
    CaseEventType,
    CaseStatus,
    ModerationAction,
    ReportReason,
)
from apps.moderation.models import ModerationCase, Report
from apps.moderation.services import (
    appeal,
    enable_security_containment,
    record_decision,
    resolve_appeal,
)
from apps.moderation.tests.factories import ModerationCaseFactory
from apps.projects.enums import ProjectStatus
from apps.projects.tests.factories import ProjectFactory

pytestmark = [pytest.mark.django_db]


def decided_case(**kwargs) -> tuple:
    case = ModerationCaseFactory(status=CaseStatus.UNDER_REVIEW, **kwargs)
    record_decision(
        SuperAdminFactory(),
        case,
        ModerationAction.CONTENT_RESTRICTION,
        ReportReason.UNLAWFUL_CONTENT,
        comment="restricted pending legal review",
    )
    case.refresh_from_db()
    return case, case.report.reporter


@pytest.mark.integration
def test_appeal_moves_case_to_appealed_with_pending_status():
    """BR-010: every enforcement decision has an appeal path that reopens the case."""
    case, member = decided_case()

    appealed = appeal(member, case, "the restricted content is my own licensed work")

    assert appealed.status == CaseStatus.APPEALED
    assert appealed.appeal_status == AppealStatus.PENDING
    assert appealed.appealed_at is not None
    assert appealed.appeal_text == "the restricted content is my own licensed work"
    assert appealed.events.filter(event=CaseEventType.APPEALED, actor=member).exists()
    assert AuditEvent.objects.filter(
        action="moderation.case.appeal", object_id=str(case.pk)
    ).exists()


@pytest.mark.integration
def test_appeal_requires_grounds_and_a_decided_case():
    """BR-010/ADM-007: only actioned cases can be appealed, and grounds are mandatory."""
    member = UserFactory()
    fresh_case = ModerationCaseFactory(status=CaseStatus.NEW)
    with pytest.raises(Exception) as excinfo:
        appeal(member, fresh_case, "grounds")
    assert type(excinfo.value).__name__ == "AppealError"

    case, _ = decided_case()
    with pytest.raises(Exception) as excinfo:
        appeal(member, case, "   ")
    assert type(excinfo.value).__name__ == "AppealError"
    case.refresh_from_db()
    assert case.status == CaseStatus.ACTION_TAKEN


@pytest.mark.integration
def test_no_second_appeal_while_pending():
    """BR-010: one pending appeal at a time."""
    case, member = decided_case()
    appeal(member, case, "first appeal")
    with pytest.raises(Exception) as excinfo:
        appeal(member, case, "second appeal")
    assert type(excinfo.value).__name__ == "AppealError"


@pytest.mark.integration
def test_appeal_blocked_during_urgent_security_containment():
    """BR-010: urgent security containment is the audited exception to the appeal path."""
    super_admin = SuperAdminFactory()
    case = ModerationCaseFactory(status=CaseStatus.ESCALATED)
    enable_security_containment(super_admin, case, "active exploit containment")
    record_decision(super_admin, case, ModerationAction.UNPUBLISH, ReportReason.MALWARE)
    case.refresh_from_db()

    with pytest.raises(Exception) as excinfo:
        appeal(UserFactory(), case, "I contest the takedown")
    assert type(excinfo.value).__name__ == "SecurityContainmentError"
    case.refresh_from_db()
    assert case.status == CaseStatus.ACTION_TAKEN
    assert case.appeal_status == ""


@pytest.mark.integration
def test_resolve_appeal_upheld_keeps_enforcement():
    """ADM-007: an upheld appeal leaves the enforcement action in place with audit."""
    case, member = decided_case()
    appeal(member, case, "grounds for appeal")
    super_admin = SuperAdminFactory()

    resolved = resolve_appeal(super_admin, case, AppealStatus.UPHELD, "evidence confirmed")

    assert resolved.status == CaseStatus.ACTION_TAKEN
    assert resolved.appeal_status == AppealStatus.UPHELD
    assert resolved.appeal_decided_by == super_admin
    assert resolved.appeal_decided_at is not None
    assert resolved.events.filter(event=CaseEventType.DECIDED, actor=super_admin).exists()
    assert AuditEvent.objects.filter(
        action="moderation.case.appeal_resolve", object_id=str(case.pk)
    ).exists()


@pytest.mark.integration
def test_resolve_appeal_overturned_reinstates_content():
    """ADM-007: an overturned appeal reinstates the content and records reinstatement."""
    case, member = decided_case()
    appeal(member, case, "the material is lawfully published")
    super_admin = SuperAdminFactory()

    resolved = resolve_appeal(super_admin, case, AppealStatus.OVERTURNED, "misfiled report")

    assert resolved.status == CaseStatus.CLOSED_NO_ACTION
    assert resolved.appeal_status == AppealStatus.OVERTURNED
    assert resolved.events.filter(event=CaseEventType.REINSTATED, actor=super_admin).exists()
    audit = AuditEvent.objects.get(action="moderation.case.appeal_resolve", object_id=str(case.pk))
    assert audit.after == {
        "status": CaseStatus.CLOSED_NO_ACTION,
        "appeal_status": AppealStatus.OVERTURNED,
        "restoration": {
            "target_type": "project",
            "before": {"status": ProjectStatus.DRAFT},
            "enforced": {"status": ProjectStatus.DRAFT},
        },
    }


@pytest.mark.integration
def test_overturned_appeal_restores_project_status_from_enforcement_provenance():
    """ADM-007/BR-010: an overturned project takedown restores its exact prior status."""
    project = ProjectFactory(status=ProjectStatus.OPEN_FOR_CONTRIBUTION)
    case = ModerationCase.objects.create(
        report=Report.objects.create(
            reporter=UserFactory(), target=project, reason=ReportReason.SPAM
        ),
        status=CaseStatus.UNDER_REVIEW,
    )
    record_decision(SuperAdminFactory(), case, ModerationAction.UNPUBLISH, ReportReason.SPAM)
    case.refresh_from_db()
    appeal(case.report.reporter, case, "the listing was compliant")

    resolve_appeal(SuperAdminFactory(), case, AppealStatus.OVERTURNED, "report withdrawn")

    project.refresh_from_db()
    case.refresh_from_db()
    assert project.status == ProjectStatus.OPEN_FOR_CONTRIBUTION
    assert case.enforcement_provenance == {
        "target_type": "project",
        "before": {"status": ProjectStatus.OPEN_FOR_CONTRIBUTION},
        "enforced": {"status": ProjectStatus.DRAFT},
    }
    assert AuditEvent.objects.filter(
        action="project.moderation.appeal_restored", object_id=str(project.pk)
    ).exists()


@pytest.mark.integration
def test_overturned_appeal_restores_blog_moderation_state_from_enforcement_provenance():
    """ADM-007/BLG-006: an overturned blog restriction restores its prior moderation state."""
    post = BlogPostFactory(moderation_state=BlogModerationState.UNDER_REVIEW)
    case = ModerationCase.objects.create(
        report=Report.objects.create(reporter=UserFactory(), target=post, reason=ReportReason.SPAM),
        status=CaseStatus.UNDER_REVIEW,
    )
    record_decision(
        SuperAdminFactory(), case, ModerationAction.CONTENT_RESTRICTION, ReportReason.SPAM
    )
    case.refresh_from_db()
    appeal(case.report.reporter, case, "the listing was compliant")

    resolve_appeal(SuperAdminFactory(), case, AppealStatus.OVERTURNED, "report withdrawn")

    post.refresh_from_db()
    assert post.moderation_state == BlogModerationState.UNDER_REVIEW
    assert AuditEvent.objects.filter(
        action="blog.moderation.appeal_restored", object_id=str(post.pk)
    ).exists()


@pytest.mark.integration
def test_overturned_appeal_restores_account_activity_from_enforcement_provenance():
    """ADM-007/AUTH-009: an overturned suspension restores an account active before enforcement."""
    member = UserFactory(is_active=True)
    case = ModerationCase.objects.create(
        report=Report.objects.create(
            reporter=UserFactory(), target=member, reason=ReportReason.HARASSMENT
        ),
        status=CaseStatus.UNDER_REVIEW,
    )
    record_decision(
        SuperAdminFactory(), case, ModerationAction.ACCOUNT_SUSPENSION, ReportReason.HARASSMENT
    )
    case.refresh_from_db()
    appeal(case.report.reporter, case, "the suspension was incorrect")

    resolve_appeal(SuperAdminFactory(), case, AppealStatus.OVERTURNED, "report withdrawn")

    member.refresh_from_db()
    assert member.is_active is True
    assert AuditEvent.objects.filter(
        action="account.moderation.appeal_restored", object_id=str(member.pk)
    ).exists()


@pytest.mark.integration
def test_overturned_appeal_preserves_later_target_changes():
    """ADM-007/SEC-008: an appeal never overwrites target state changed after enforcement."""
    project = ProjectFactory(status=ProjectStatus.OPEN_FOR_CONTRIBUTION)
    case = ModerationCase.objects.create(
        report=Report.objects.create(
            reporter=UserFactory(), target=project, reason=ReportReason.SPAM
        ),
        status=CaseStatus.UNDER_REVIEW,
    )
    record_decision(SuperAdminFactory(), case, ModerationAction.UNPUBLISH, ReportReason.SPAM)
    case.refresh_from_db()
    appeal(case.report.reporter, case, "the listing was compliant")
    project.status = ProjectStatus.ARCHIVED
    project.save(update_fields=["status", "updated_at"])

    with pytest.raises(Exception) as excinfo:
        resolve_appeal(SuperAdminFactory(), case, AppealStatus.OVERTURNED, "report withdrawn")

    assert type(excinfo.value).__name__ == "AppealRestorationError"
    project.refresh_from_db()
    case.refresh_from_db()
    assert project.status == ProjectStatus.ARCHIVED
    assert case.status == CaseStatus.APPEALED
    assert AuditEvent.objects.filter(action="moderation.case.appeal_restore.denied").exists()


@pytest.mark.integration
def test_overturned_appeal_never_reverses_security_containment():
    """BR-010/SEC-008: containment enabled after an appeal blocks reinstatement and is preserved."""
    project = ProjectFactory(status=ProjectStatus.OPEN_FOR_CONTRIBUTION)
    case = ModerationCase.objects.create(
        report=Report.objects.create(
            reporter=UserFactory(), target=project, reason=ReportReason.MALWARE
        ),
        status=CaseStatus.UNDER_REVIEW,
    )
    super_admin = SuperAdminFactory()
    record_decision(super_admin, case, ModerationAction.UNPUBLISH, ReportReason.MALWARE)
    case.refresh_from_db()
    appeal(case.report.reporter, case, "the listing was compliant")
    enable_security_containment(super_admin, case, "new threat intelligence")

    with pytest.raises(Exception) as excinfo:
        resolve_appeal(super_admin, case, AppealStatus.OVERTURNED, "report withdrawn")

    assert type(excinfo.value).__name__ == "AppealRestorationError"
    project.refresh_from_db()
    case.refresh_from_db()
    assert project.status == ProjectStatus.DRAFT
    assert case.security_containment is True
    assert case.status == CaseStatus.APPEALED


@pytest.mark.integration
def test_resolve_appeal_requires_super_admin_pending_appeal_and_reason():
    """ADM-007/§4.2: appeal resolution is a privileged, reasoned action on a pending appeal."""
    case, member = decided_case()
    appeal(member, case, "grounds")

    with pytest.raises(Exception) as excinfo:
        resolve_appeal(UserFactory(), case, AppealStatus.UPHELD, "reason")
    assert type(excinfo.value).__name__ == "ModerationAuthorizationError"

    super_admin = SuperAdminFactory()
    with pytest.raises(Exception) as excinfo:
        resolve_appeal(super_admin, case, "deferred", "reason")
    assert type(excinfo.value).__name__ == "AppealError"

    with pytest.raises(Exception) as excinfo:
        resolve_appeal(super_admin, case, AppealStatus.UPHELD, " ")
    assert type(excinfo.value).__name__ == "AppealError"

    resolved = resolve_appeal(super_admin, case, AppealStatus.UPHELD, "confirmed")
    with pytest.raises(Exception) as excinfo:
        resolve_appeal(super_admin, resolved, AppealStatus.UPHELD, "again")
    assert type(excinfo.value).__name__ == "AppealError"
