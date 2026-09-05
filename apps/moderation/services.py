"""Moderation workflow services (ADM-003, ADM-004, ADM-005, ADM-007, BR-010).

SRS 13.2 principles encoded here:
- least restrictive action: record_decision demands a structured reason so the
  proportionality of every enforcement choice is documented and auditable
- routine review is separated from security incident handling: security-class
  reasons file straight into the ESCALATED security queue
- affected users get an appeal path, except urgent security containment, which
  is an explicit case flag with a mandatory audited reason
- reporters and evidence are confidential: public_summary never exposes them
"""

import logging
from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from apps.accounts.services import require_privileged_mfa
from apps.audit.models import AuditEvent
from apps.audit.services import record_audit
from apps.blogs.enums import BlogModerationState
from apps.blogs.models import BlogPost
from apps.blogs.services import restrict_post
from apps.moderation.enums import (
    AppealStatus,
    CaseEventType,
    CaseStatus,
    ModerationAction,
    ReportReason,
)
from apps.moderation.models import ModerationCase, ModerationEvent, Report
from apps.projects.enums import ProjectStatus
from apps.projects.models import Project
from apps.taxonomy.fields import normalize_nfc

logger = logging.getLogger(__name__)

SECURITY_REASONS = frozenset(
    {ReportReason.SECURITY_CONCERN, ReportReason.MALWARE, ReportReason.UNSAFE_LINK}
)

DECISION_TARGET_STATUS: dict[str, str] = {
    ModerationAction.NO_ACTION: CaseStatus.CLOSED_NO_ACTION,
    ModerationAction.WARNING: CaseStatus.ACTION_TAKEN,
    ModerationAction.CONTENT_RESTRICTION: CaseStatus.ACTION_TAKEN,
    ModerationAction.UNPUBLISH: CaseStatus.ACTION_TAKEN,
    ModerationAction.ACCOUNT_SUSPENSION: CaseStatus.ACTION_TAKEN,
    ModerationAction.ESCALATION: CaseStatus.ESCALATED,
}

WORKING_STATUSES = frozenset({CaseStatus.NEW, CaseStatus.UNDER_REVIEW, CaseStatus.ESCALATED})

EXPORT_MIN_PURPOSE_LENGTH = 20
EXPORT_RATE_LIMIT = 10
EXPORT_RATE_WINDOW = timedelta(hours=1)


class ModerationServiceError(Exception):
    """Base error for moderation workflow violations."""


class InvalidReportReason(ModerationServiceError):
    """A report was filed outside the structured ADM-003 reason set."""


class InvalidReportTarget(ModerationServiceError):
    """A report was filed against a missing or unsaved target object."""


class ModerationAuthorizationError(ModerationServiceError):
    """The actor may not perform this moderation action (SRS 4.2)."""


class ModerationDecisionError(ModerationServiceError):
    """An illegal moderation decision or case transition (ADM-004, BR-010)."""


class AppealError(ModerationServiceError):
    """An appeal could not be filed or resolved (ADM-007, BR-010)."""


class AppealOwnershipError(AppealError):
    """The appeal was not filed by the case reporter (ADM-007)."""


class AppealRestorationError(AppealError):
    """An overturned appeal cannot safely restore the original target state."""


class SecurityContainmentError(AppealError):
    """No appeal path exists during urgent security containment (BR-010)."""


class ExportPurposeError(ModerationServiceError):
    """A privileged export lacked a purpose-limited justification (ADM-005)."""


class ExportRateLimitError(ModerationServiceError):
    """A privileged export exceeded the per-admin rate limit (ADM-005, SEC-006)."""


def _is_super_admin(actor) -> bool:
    return bool(
        actor
        and getattr(actor, "is_active", False)
        and getattr(actor, "is_authenticated", False)
        and getattr(actor, "is_superuser", False)
    )


def _require_super_admin(actor, *, action: str, obj=None) -> None:
    if _is_super_admin(actor):
        require_privileged_mfa(
            actor, action=action, obj=obj, error_type=ModerationAuthorizationError
        )
        return
    record_audit(actor=actor, action=f"{action}.denied", obj=obj, result="failure")
    raise ModerationAuthorizationError(f"{action} requires an active Super Admin")


def _require_text(value: str) -> str:
    return value.strip() if isinstance(value, str) else ""


def _case_payload(case: ModerationCase) -> dict:
    return {
        "status": case.status,
        "action": case.action,
        "action_reason": case.action_reason,
    }


def _enforcement_provenance(target, action: str) -> dict:
    if action in {ModerationAction.CONTENT_RESTRICTION, ModerationAction.UNPUBLISH}:
        if isinstance(target, BlogPost):
            return {
                "target_type": "blog_post",
                "before": {"moderation_state": target.moderation_state},
                "enforced": {"moderation_state": BlogModerationState.RESTRICTED},
            }
        if isinstance(target, Project):
            return {
                "target_type": "project",
                "before": {"status": target.status},
                "enforced": {"status": ProjectStatus.DRAFT},
            }
    if action == ModerationAction.ACCOUNT_SUSPENSION and hasattr(target, "is_active"):
        return {
            "target_type": "account",
            "before": {"is_active": target.is_active},
            "enforced": {"is_active": False},
        }
    return {}


def file_report(reporter, target_obj, reason, details="", evidence_url="") -> Report:
    """File a structured report and open its ModerationCase (ADM-003, A7).

    Security-class reasons open the case directly in the ESCALATED security
    queue, separating security incidents from routine review (SRS 13.2).
    """
    if reason not in ReportReason.values:
        raise InvalidReportReason(f"{reason!r} is not a structured report reason (ADM-003)")
    if target_obj is None or getattr(target_obj, "pk", None) is None:
        raise InvalidReportTarget("a report target must be a saved model instance")

    with transaction.atomic():
        report = Report.objects.create(
            reporter=reporter,
            content_type=ContentType.objects.get_for_model(target_obj),
            object_id=str(target_obj.pk),
            reason=reason,
            details=details,
            evidence_url=evidence_url,
        )
        case = ModerationCase.objects.create(
            report=report,
            status=(CaseStatus.ESCALATED if reason in SECURITY_REASONS else CaseStatus.NEW),
        )
        ModerationEvent.objects.create(
            case=case, actor=reporter, event=CaseEventType.CREATED, comment=reason
        )
    record_audit(actor=reporter, action="moderation.report.file", obj=case)
    return report


def assign_case(super_admin, case: ModerationCase) -> ModerationCase:
    """Assign a queued case to a Super Admin reviewer (ADM-002)."""
    _require_super_admin(super_admin, action="moderation.case.assign", obj=case)
    if case.status not in WORKING_STATUSES:
        raise ModerationDecisionError(f"a case in status {case.status} cannot be assigned")
    before = _case_payload(case)
    with transaction.atomic():
        case.assigned_to = super_admin
        case.status = CaseStatus.UNDER_REVIEW
        case.save(update_fields=["assigned_to", "status", "updated_at"])
        ModerationEvent.objects.create(case=case, actor=super_admin, event=CaseEventType.ASSIGNED)
    record_audit(
        actor=super_admin,
        action="moderation.case.assign",
        obj=case,
        before=before,
        after=_case_payload(case),
    )
    return case


def record_decision(super_admin, case: ModerationCase, action, reason, comment=""):
    """Record a graduated moderation decision (ADM-004, BR-010).

    Every action — from no_action to account_suspension — must carry a
    structured reason documenting why it is the least restrictive action that
    protects people, the platform, and public trust (SRS 13.2). The decision is
    written to the case timeline and the audit log.
    """
    _require_super_admin(super_admin, action="moderation.case.decide", obj=case)
    if action not in ModerationAction.values:
        raise ModerationDecisionError(f"{action!r} is not a graduated moderation action (ADM-004)")
    if _require_text(reason) not in ReportReason.values:
        record_audit(
            actor=super_admin,
            action="moderation.case.decide.denied",
            obj=case,
            result="failure",
        )
        raise ModerationDecisionError("a moderation decision requires a structured reason (BR-010)")
    if case.status not in WORKING_STATUSES:
        raise ModerationDecisionError(f"a case in status {case.status} cannot be decided")

    before = _case_payload(case)
    event_type = (
        CaseEventType.ESCALATED
        if action == ModerationAction.ESCALATION
        else CaseEventType.ACTION_TAKEN
    )
    with transaction.atomic():
        enforcement_provenance = _enforce_action(super_admin, case, action)
        case.action = action
        case.action_reason = reason
        case.enforcement_provenance = enforcement_provenance
        case.decision_comment = comment
        case.decided_by = super_admin
        case.decided_at = timezone.now()
        case.status = DECISION_TARGET_STATUS[action]
        case.save(
            update_fields=[
                "action",
                "action_reason",
                "enforcement_provenance",
                "decision_comment",
                "decided_by",
                "decided_at",
                "status",
                "updated_at",
            ]
        )
        ModerationEvent.objects.create(
            case=case, actor=super_admin, event=event_type, comment=comment or reason
        )
    record_audit(
        actor=super_admin,
        action="moderation.case.decide",
        obj=case,
        before=before,
        after=_case_payload(case),
    )
    return case


def _enforce_action(super_admin, case: ModerationCase, action: str) -> dict:
    target = case.report.target
    provenance = _enforcement_provenance(target, action)
    if action in {ModerationAction.CONTENT_RESTRICTION, ModerationAction.UNPUBLISH}:
        if isinstance(target, BlogPost):
            restrict_post(super_admin, target)
            return provenance
        if isinstance(target, Project):
            before = {"status": target.status}
            target.status = ProjectStatus.DRAFT
            target.save(update_fields=["status", "updated_at"])
            record_audit(
                actor=super_admin,
                action="project.moderation.unpublished",
                obj=target,
                before=before,
                after={"status": target.status},
            )
            return provenance
        raise ModerationDecisionError("content action requires a reported project or blog listing")
    if action == ModerationAction.ACCOUNT_SUSPENSION:
        if not hasattr(target, "is_active"):
            raise ModerationDecisionError("account suspension requires a reported account")
        before = {"is_active": target.is_active}
        target.is_active = False
        target.save(update_fields=["is_active"])
        record_audit(
            actor=super_admin,
            action="account.moderation.suspended",
            obj=target,
            before=before,
            after={"is_active": False},
        )
        return provenance
    return {}


def enable_security_containment(super_admin, case: ModerationCase, reason):
    """Flag a case as urgent security containment (BR-010 exception).

    While the flag is set the appeal path is not required; the reason is
    mandatory and audited so the exception is always accountable.
    """
    _require_super_admin(super_admin, action="moderation.case.contain", obj=case)
    if not _require_text(reason):
        record_audit(
            actor=super_admin,
            action="moderation.case.contain.denied",
            obj=case,
            result="failure",
        )
        raise ModerationDecisionError("urgent security containment requires a reason (BR-010)")
    with transaction.atomic():
        case.security_containment = True
        case.save(update_fields=["security_containment", "updated_at"])
        ModerationEvent.objects.create(
            case=case, actor=super_admin, event=CaseEventType.ESCALATED, comment=reason
        )
    record_audit(
        actor=super_admin,
        action="moderation.case.contain",
        obj=case,
        after={"security_containment": True, "reason": reason},
    )
    return case


def appeal(member, case: ModerationCase, grounds):
    """File an appeal against an actioned case (BR-010, ADM-007)."""
    if not _require_text(grounds):
        raise AppealError("an appeal requires grounds")
    if case.security_containment:
        raise SecurityContainmentError("no appeal path during urgent security containment (BR-010)")
    if case.status != CaseStatus.ACTION_TAKEN:
        raise AppealError(f"a case in status {case.status} cannot be appealed")
    if case.report.reporter_id != getattr(member, "pk", None):
        record_audit(
            actor=member,
            action="moderation.case.appeal.denied",
            obj=case,
            result="failure",
        )
        raise AppealOwnershipError("only the reporter may appeal this case")
    if case.appeal_status == AppealStatus.PENDING:
        raise AppealError("an appeal is already pending")

    with transaction.atomic():
        case.appeal_text = grounds
        case.appealed_at = timezone.now()
        case.appeal_status = AppealStatus.PENDING
        case.status = CaseStatus.APPEALED
        case.save(
            update_fields=[
                "appeal_text",
                "appealed_at",
                "appeal_status",
                "status",
                "updated_at",
            ]
        )
        ModerationEvent.objects.create(
            case=case, actor=member, event=CaseEventType.APPEALED, comment=grounds
        )
    record_audit(
        actor=member,
        action="moderation.case.appeal",
        obj=case,
        after={"appeal_status": AppealStatus.PENDING},
    )
    return case


def resolve_appeal(super_admin, case: ModerationCase, outcome, reason):
    """Resolve a pending appeal (ADM-007).

    UPHELD keeps the enforcement action; OVERTURNED reinstates the content and
    closes the case without action. Either way the affected user's path is
    audited end to end.
    """
    _require_super_admin(super_admin, action="moderation.case.appeal_resolve", obj=case)
    if outcome not in {AppealStatus.UPHELD, AppealStatus.OVERTURNED}:
        raise AppealError(f"{outcome!r} is not an appeal outcome")
    if not _require_text(reason):
        raise AppealError("appeal resolution requires a reason (ADM-007)")
    if case.status != CaseStatus.APPEALED or case.appeal_status != AppealStatus.PENDING:
        raise AppealError("no pending appeal to resolve")

    before = {"status": case.status, "appeal_status": case.appeal_status}
    try:
        with transaction.atomic():
            if outcome == AppealStatus.OVERTURNED:
                _restore_enforcement(super_admin, case)
            case.appeal_status = outcome
            case.appeal_decided_by = super_admin
            case.appeal_decided_at = timezone.now()
            case.status = (
                CaseStatus.ACTION_TAKEN
                if outcome == AppealStatus.UPHELD
                else CaseStatus.CLOSED_NO_ACTION
            )
            case.save(
                update_fields=[
                    "appeal_status",
                    "appeal_decided_by",
                    "appeal_decided_at",
                    "status",
                    "updated_at",
                ]
            )
            ModerationEvent.objects.create(
                case=case, actor=super_admin, event=CaseEventType.DECIDED, comment=reason
            )
            if outcome == AppealStatus.OVERTURNED:
                ModerationEvent.objects.create(
                    case=case, actor=super_admin, event=CaseEventType.REINSTATED, comment=reason
                )
    except AppealRestorationError:
        record_audit(
            actor=super_admin,
            action="moderation.case.appeal_restore.denied",
            obj=case,
            after={"action": case.action},
            result="failure",
        )
        raise
    after = {"status": case.status, "appeal_status": case.appeal_status}
    if outcome == AppealStatus.OVERTURNED:
        after["restoration"] = case.enforcement_provenance
    record_audit(
        actor=super_admin,
        action="moderation.case.appeal_resolve",
        obj=case,
        before=before,
        after=after,
    )
    return case


def _restore_enforcement(super_admin, case: ModerationCase) -> None:
    if case.security_containment:
        raise AppealRestorationError("security containment prevents target restoration")
    provenance = case.enforcement_provenance
    target = case.report.target
    if not provenance:
        return
    if target is None:
        raise AppealRestorationError("reported target no longer exists")
    target_type = provenance.get("target_type")
    before = provenance.get("before")
    enforced = provenance.get("enforced")
    if not isinstance(before, dict) or not isinstance(enforced, dict):
        raise AppealRestorationError("enforcement provenance is invalid")
    if target_type == "project" and isinstance(target, Project):
        _restore_target_state(
            super_admin,
            target,
            before,
            enforced,
            field="status",
            audit_action="project.moderation.appeal_restored",
            update_fields=["status", "updated_at"],
        )
        return
    if target_type == "blog_post" and isinstance(target, BlogPost):
        _restore_target_state(
            super_admin,
            target,
            before,
            enforced,
            field="moderation_state",
            audit_action="blog.moderation.appeal_restored",
            update_fields=["moderation_state", "updated_at"],
        )
        return
    if target_type == "account" and hasattr(target, "is_active"):
        _restore_target_state(
            super_admin,
            target,
            before,
            enforced,
            field="is_active",
            audit_action="account.moderation.appeal_restored",
            update_fields=["is_active"],
        )
        return
    raise AppealRestorationError("enforcement provenance does not match the reported target")


def _restore_target_state(
    actor,
    target,
    before: dict,
    enforced: dict,
    *,
    field: str,
    audit_action: str,
    update_fields: list[str],
) -> None:
    if set(before) != {field} or set(enforced) != {field}:
        raise AppealRestorationError("enforcement provenance has unsupported fields")
    if getattr(target, field) != enforced[field]:
        raise AppealRestorationError("reported target changed after enforcement")
    setattr(target, field, before[field])
    target.save(update_fields=update_fields)
    record_audit(
        actor=actor,
        action=audit_action,
        obj=target,
        before=enforced,
        after=before,
    )


def _filter_field_names(queryset) -> list[str]:
    def walk(node) -> list[str]:
        names = []
        for child in getattr(node, "children", []):
            if hasattr(child, "children"):
                names.extend(walk(child))
            elif (field := getattr(getattr(child, "lhs", None), "field", None)) is not None:
                names.append(field.name)
        return names

    return sorted(set(walk(queryset.query.where)))


def export_cases(super_admin, queryset, purpose: str) -> list[ModerationCase]:
    """Privileged case export stub (ADM-005).

    Access-controlled and purpose-limited: the audit entry records purpose,
    count, and the filtered field names — never case contents.
    """
    _require_super_admin(super_admin, action="moderation.case.export")
    if not _require_text(purpose):
        record_audit(
            actor=super_admin,
            action="moderation.case.export.denied",
            result="failure",
        )
        raise ExportPurposeError("a privileged export requires a purpose (ADM-005)")

    cases = list(queryset)
    filters = _filter_field_names(queryset)
    record_audit(
        actor=super_admin,
        action="moderation.case.export",
        after={
            "purpose": purpose,
            "count": len(cases),
            "model": queryset.model._meta.label,
            "filters": filters,
        },
    )
    logger.info(
        "moderation case export by actor %s: purpose=%s count=%d filters=%s",
        getattr(super_admin, "pk", None),
        purpose,
        len(cases),
        filters,
    )
    return cases


def _require_export_purpose(super_admin, case: ModerationCase, purpose) -> str:
    purpose = normalize_nfc(_require_text(purpose))
    if len(purpose) < EXPORT_MIN_PURPOSE_LENGTH:
        record_audit(
            actor=super_admin,
            action="moderation.case.export.denied",
            obj=case,
            result="failure",
        )
        raise ExportPurposeError("a privileged export requires a structured purpose (ADM-005)")
    return purpose


def _recent_export_count(actor) -> int:
    return AuditEvent.objects.filter(
        actor=actor,
        action="moderation.case.export",
        created_at__gte=timezone.now() - EXPORT_RATE_WINDOW,
    ).count()


def export_case_record(super_admin, case: ModerationCase, purpose: str) -> dict:
    """Purpose-limited export of one confidential case record (ADM-005, SEC-008).

    Access-controlled, MFA-verified Super Admin only. The declared purpose must
    meet the structured minimum length. The audit entry records the purpose and
    the case id — never the exported payload content. Exports beyond the hourly
    per-admin rate limit are refused and audited.
    """
    _require_super_admin(super_admin, action="moderation.case.export", obj=case)
    purpose = _require_export_purpose(super_admin, case, purpose)
    if _recent_export_count(super_admin) >= EXPORT_RATE_LIMIT:
        record_audit(
            actor=super_admin,
            action="moderation.case.export.denied",
            obj=case,
            after={"reason": "rate_limited"},
            result="failure",
        )
        raise ExportRateLimitError("too many privileged exports in the current window (ADM-005)")

    payload = _case_export_payload(case)
    record_audit(
        actor=super_admin,
        action="moderation.case.export",
        obj=case,
        after={"purpose": purpose},
    )
    logger.info(
        "moderation case record export by actor %s: case=%s",
        getattr(super_admin, "pk", None),
        case.pk,
    )
    return payload


def _case_export_payload(case: ModerationCase) -> dict:
    report = case.report
    return {
        "case": {
            "id": case.pk,
            "status": case.status,
            "action": case.action,
            "action_reason": case.action_reason,
            "decision_comment": case.decision_comment,
            "enforcement_provenance": case.enforcement_provenance,
            "security_containment": case.security_containment,
            "assigned_to": case.assigned_to.username if case.assigned_to_id else None,
            "decided_by": case.decided_by.username if case.decided_by_id else None,
            "decided_at": case.decided_at.isoformat() if case.decided_at else None,
            "appeal_status": case.appeal_status,
            "appeal_text": case.appeal_text,
            "appealed_at": case.appealed_at.isoformat() if case.appealed_at else None,
            "appeal_decided_by": case.appeal_decided_by.username
            if case.appeal_decided_by_id
            else None,
            "appeal_decided_at": case.appeal_decided_at.isoformat()
            if case.appeal_decided_at
            else None,
            "created_at": case.created_at.isoformat(),
            "updated_at": case.updated_at.isoformat(),
        },
        "report": {
            "id": report.pk,
            "reason": report.reason,
            "details": report.details,
            "evidence_url": report.evidence_url,
            "reporter": report.reporter.username if report.reporter_id else None,
            "target_model": report.content_type.model,
            "target_id": report.object_id,
            "created_at": report.created_at.isoformat(),
        },
        "events": [
            {
                "event": event.event,
                "actor": event.actor.username if event.actor_id else None,
                "comment": event.comment,
                "created_at": event.created_at.isoformat(),
            }
            for event in case.events.select_related("actor")
        ],
    }


def public_summary(case: ModerationCase) -> dict:
    """Confidentiality-safe case summary (SRS 13.2, A7).

    Never includes the reporter identity, the reporter's details, or the
    evidence URL; those stay Confidential (SRS 9.2).
    """
    report = case.report
    return {
        "id": case.pk,
        "status": case.status,
        "reason": report.reason,
        "target_model": report.content_type.model,
        "action": case.action,
        "created_at": case.created_at.isoformat(),
    }
