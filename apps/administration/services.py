import logging
from datetime import timedelta

from django.contrib.sessions.models import Session
from django.db import transaction
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.accounts.models import User, UserSession
from apps.accounts.permissions import is_super_admin
from apps.accounts.services import require_privileged_mfa
from apps.administration.enums import ChangeStatus, GrantAction
from apps.administration.models import FeatureFlag, FeatureFlagChange, SuperAdminGrant
from apps.audit.services import record_audit

logger = logging.getLogger(__name__)


class AdministrationServiceError(Exception):
    """Base error for privileged administration operations."""


class AdministrationAuthorizationError(AdministrationServiceError):
    """The actor is not a Super Admin (ADM-001)."""


class AdministrationMFARequiredError(AdministrationServiceError):
    """The actor holds the role but has no verified MFA session (AUTH-005)."""


class FourEyesRequiredError(AdministrationServiceError):
    """A member-impacting switch cannot be changed by one Super Admin alone (D5.7)."""


class SelfApprovalError(AdministrationServiceError):
    """The second Super Admin must not be the one who proposed the change (D5.7)."""


class ChangeNotPendingError(AdministrationServiceError):
    """The change has already been applied or withdrawn (D5.7)."""


class MissingChangeReasonError(AdministrationServiceError):
    """Every configuration change records why it was made (D5.7)."""


def _require_super_admin(actor, *, action: str, obj=None) -> None:
    """ADM-001/AUTH-005: authorize at the service boundary, not only in the view."""
    if not is_super_admin(actor):
        record_audit(
            actor=actor if getattr(actor, "is_authenticated", False) else None,
            action=action,
            obj=obj,
            result="denied",
        )
        raise AdministrationAuthorizationError(action)
    require_privileged_mfa(actor, action=action, obj=obj, error_type=AdministrationMFARequiredError)


def _require_reason(reason: str) -> str:
    cleaned = (reason or "").strip()
    if not cleaned:
        raise MissingChangeReasonError("a configuration change must record a reason")
    return cleaned


def flag_enabled(key: str) -> bool:
    """ADM-001: report whether a named capability is switched on, defaulting to off."""
    return FeatureFlag.objects.filter(key=key, is_enabled=True).exists()


def pending_changes():
    """D5.7: changes waiting for a second Super Admin to confirm."""
    return (
        FeatureFlagChange.objects.filter(status=ChangeStatus.PENDING)
        .select_related("flag", "proposed_by")
        .order_by("proposed_at")
    )


def _change_payload(change: FeatureFlagChange) -> dict:
    return {
        "flag": change.flag.key,
        "version": change.version,
        "to_enabled": change.to_enabled,
        "status": change.status,
        "reason": change.reason,
        "proposed_by": change.proposed_by.username,
        "approved_by": change.approved_by.username if change.approved_by else None,
    }


def request_feature_flag_change(actor, flag: FeatureFlag, *, is_enabled: bool, reason: str):
    """D5.7: record a switch change, holding it for a second approver when members are affected.

    A switch scoped to members is not applied on the proposer's authority: it is
    recorded as pending until a different Super Admin confirms it. Every other
    switch applies immediately, and is still versioned and attributed.
    """
    _require_super_admin(actor, action="administration.feature_flag_change", obj=flag)
    cleaned = _require_reason(reason)
    return _record_change(actor, flag, is_enabled=is_enabled, reason=cleaned)


@transaction.atomic
def _record_change(actor, flag: FeatureFlag, *, is_enabled: bool, reason: str):
    flag = FeatureFlag.objects.select_for_update().get(pk=flag.pk)
    change = FeatureFlagChange.objects.create(
        flag=flag,
        version=flag.version + 1,
        from_enabled=flag.is_enabled,
        to_enabled=is_enabled,
        reason=reason,
        proposed_by=actor,
        status=ChangeStatus.PENDING,
    )
    if flag.requires_four_eyes:
        record_audit(
            actor=actor,
            action="administration.feature_flag_change_proposed",
            obj=flag,
            before={"key": flag.key, "is_enabled": flag.is_enabled},
            after=_change_payload(change),
        )
        return change
    return _apply_change(actor, change, flag=flag)


def approve_feature_flag_change(actor, change: FeatureFlagChange) -> FeatureFlagChange:
    """D5.7: a second, different Super Admin confirms a member-impacting change."""
    _require_super_admin(
        actor, action="administration.feature_flag_change_approve", obj=change.flag
    )
    if change.status != ChangeStatus.PENDING:
        raise ChangeNotPendingError(change.status)
    if change.proposed_by_id == getattr(actor, "pk", None):
        record_audit(
            actor=actor,
            action="administration.feature_flag_change_approve",
            obj=change.flag,
            after=_change_payload(change),
            result="denied",
        )
        raise SelfApprovalError("a change must be confirmed by a different Super Admin")
    return _apply_change(actor, change)


@transaction.atomic
def _apply_change(actor, change: FeatureFlagChange, *, flag=None) -> FeatureFlagChange:
    change = (
        FeatureFlagChange.objects.select_for_update()
        .select_related("flag", "proposed_by", "approved_by")
        .get(pk=change.pk)
    )
    if change.status != ChangeStatus.PENDING:
        raise ChangeNotPendingError(change.status)
    flag = flag or FeatureFlag.objects.select_for_update().get(pk=change.flag_id)
    before = {"key": flag.key, "is_enabled": flag.is_enabled, "version": flag.version}

    flag.is_enabled = change.to_enabled
    flag.version = change.version
    flag.reason = change.reason
    flag.updated_by = actor
    flag.save(update_fields=["is_enabled", "version", "reason", "updated_by", "updated_at"])

    change.status = ChangeStatus.APPLIED
    change.approved_by = actor
    change.applied_at = timezone.now()
    change.save(update_fields=["status", "approved_by", "applied_at"])
    change.flag = flag

    record_audit(
        actor=actor,
        action="administration.feature_flag_change_applied",
        obj=flag,
        before=before,
        after=_change_payload(change),
    )
    return change


def set_feature_flag(actor, flag: FeatureFlag, *, is_enabled: bool, reason: str = ""):
    """ADM-001/D5.7: switch a capability that does not change what members see.

    Kept as the direct path for operator-facing switches. A member-impacting
    switch is refused here and must go through the proposal and approval flow.
    """
    if flag.requires_four_eyes:
        raise FourEyesRequiredError(flag.key)
    change = request_feature_flag_change(
        actor,
        flag,
        is_enabled=is_enabled,
        reason=reason or "Direct change to an operator-facing switch.",
    )
    return change.flag


def create_feature_flag(
    actor,
    *,
    key: str,
    label: str,
    description: str = "",
    scope: str = "Everyone",
    owner: str = "",
    reason: str = "",
    affects_members: bool = False,
) -> FeatureFlag:
    """ADM-001/D5.7: register a scoped, owned switch, disabled until it is switched on."""
    _require_super_admin(actor, action="administration.feature_flag_create")
    return _persist_feature_flag(
        actor,
        key=key,
        label=label,
        description=description,
        scope=scope,
        owner=owner,
        reason=reason,
        affects_members=affects_members,
    )


@transaction.atomic
def _persist_feature_flag(actor, **fields) -> FeatureFlag:
    flag = FeatureFlag.objects.create(is_enabled=False, updated_by=actor, **fields)
    record_audit(
        actor=actor,
        action="administration.feature_flag_create",
        obj=flag,
        after={
            "key": flag.key,
            "label": flag.label,
            "scope": flag.scope,
            "owner": flag.owner,
            "affects_members": flag.affects_members,
            "is_enabled": flag.is_enabled,
        },
    )
    return flag


GRANT_CONFIRMATION_WINDOW = timedelta(hours=24)


class GrantExpiredError(AdministrationServiceError):
    """The confirmation window for a Super Admin grant has closed (D5.8)."""


class RedundantGrantError(AdministrationServiceError):
    """The subject already holds, or already lacks, the Super Admin role (D5.8)."""


class LastSuperAdminError(AdministrationServiceError):
    """The platform must keep at least one Super Admin (AUTH-003)."""


def _grant_payload(grant) -> dict:
    return {
        "subject": grant.subject.username,
        "action": grant.action,
        "status": grant.status,
        "reason": grant.reason,
        "proposed_by": grant.proposed_by.username,
        "approved_by": grant.approved_by.username if grant.approved_by else None,
    }


def pending_grants(*, now=None):
    """D5.8: grants still inside their confirmation window."""
    return (
        SuperAdminGrant.objects.filter(
            status=ChangeStatus.PENDING, expires_at__gt=now or timezone.now()
        )
        .select_related("subject", "proposed_by")
        .order_by("expires_at")
    )


def propose_super_admin_grant(actor, subject, *, reason: str) -> SuperAdminGrant:
    """AUTH-003/D5.8: propose a Super Admin grant for a second Super Admin to confirm."""
    _require_super_admin(actor, action="administration.super_admin_grant_proposed", obj=subject)
    cleaned = _require_reason(reason)
    if subject.is_superuser and subject.is_active:
        raise RedundantGrantError(subject.username)
    grant = SuperAdminGrant.objects.create(
        subject=subject,
        action=GrantAction.GRANT,
        reason=cleaned,
        proposed_by=actor,
        expires_at=timezone.now() + GRANT_CONFIRMATION_WINDOW,
    )
    record_audit(
        actor=actor,
        action="administration.super_admin_grant_proposed",
        obj=subject,
        after=_grant_payload(grant),
    )
    return grant


def confirm_super_admin_grant(actor, grant: SuperAdminGrant) -> SuperAdminGrant:
    """AUTH-003/D5.8: a different Super Admin confirms a grant within the 24 hour window.

    The refusal paths run before the transaction opens: a denial or a lapse must
    survive in the audit trail even though it aborts the grant (ADM-008).
    """
    _require_super_admin(
        actor, action="administration.super_admin_grant_confirmed", obj=grant.subject
    )
    if grant.proposed_by_id == getattr(actor, "pk", None):
        record_audit(
            actor=actor,
            action="administration.super_admin_grant_confirmed",
            obj=grant.subject,
            after=_grant_payload(grant),
            result="denied",
        )
        raise SelfApprovalError("a grant must be confirmed by a different Super Admin")
    expired = False
    with transaction.atomic():
        locked_grant = (
            SuperAdminGrant.objects.select_for_update()
            .select_related("subject", "proposed_by", "approved_by")
            .get(pk=grant.pk)
        )
        if locked_grant.status != ChangeStatus.PENDING:
            raise ChangeNotPendingError(locked_grant.status)
        if locked_grant.has_expired():
            locked_grant.status = ChangeStatus.WITHDRAWN
            locked_grant.save(update_fields=["status"])
            record_audit(
                actor=actor,
                action="administration.super_admin_grant_expired",
                obj=locked_grant.subject,
                after=_grant_payload(locked_grant),
                result="failure",
            )
            expired = True
        else:
            subject = User.objects.select_for_update().get(pk=locked_grant.subject_id)
            subject.is_superuser = True
            subject.is_staff = True
            subject.save(update_fields=["is_superuser", "is_staff"])

            locked_grant.status = ChangeStatus.APPLIED
            locked_grant.approved_by = actor
            locked_grant.applied_at = timezone.now()
            locked_grant.save(update_fields=["status", "approved_by", "applied_at"])
            locked_grant.subject = subject

            record_audit(
                actor=actor,
                action="administration.super_admin_granted",
                obj=subject,
                before={"is_superuser": False},
                after=_grant_payload(locked_grant),
            )
    if expired:
        raise GrantExpiredError(grant.pk)
    return locked_grant


def revoke_super_admin(actor, subject, *, reason: str) -> SuperAdminGrant:
    """AUTH-003/D5.8: revoke Super Admin immediately and end that person's sessions.

    Revocation takes effect at once rather than waiting for a second admin: the
    risk of leaving a compromised account privileged outweighs the confirmation.
    The person's existing audit entries stay under their own name.
    """
    _require_super_admin(actor, action="administration.super_admin_revoked", obj=subject)
    cleaned = _require_reason(reason)
    with transaction.atomic():
        active_admins = list(
            User.objects.select_for_update()
            .filter(is_superuser=True, is_active=True)
            .order_by("pk")
        )
        locked_subject = next((admin for admin in active_admins if admin.pk == subject.pk), None)
        if locked_subject is None:
            raise RedundantGrantError(subject.username)
        if len(active_admins) == 1:
            raise LastSuperAdminError(subject.username)

        locked_subject.is_superuser = False
        locked_subject.is_staff = False
        locked_subject.save(update_fields=["is_superuser", "is_staff"])
        ended = _end_sessions(locked_subject)

        grant = SuperAdminGrant.objects.create(
            subject=locked_subject,
            action=GrantAction.REVOKE,
            reason=cleaned,
            status=ChangeStatus.APPLIED,
            proposed_by=actor,
            approved_by=actor,
            expires_at=timezone.now(),
            applied_at=timezone.now(),
        )
        record_audit(
            actor=actor,
            action="administration.super_admin_revoked",
            obj=locked_subject,
            before={"is_superuser": True},
            after=_grant_payload(grant) | {"sessions_ended": ended},
        )
    return grant


def _end_sessions(subject) -> int:
    now = timezone.now()
    open_sessions = UserSession.objects.filter(user=subject, revoked_at__isnull=True)
    keys = list(open_sessions.values_list("session_key", flat=True))
    Session.objects.filter(session_key__in=keys).delete()
    return open_sessions.update(revoked_at=now)


def super_admin_roster():
    """AUTH-003/AUTH-007/D5.8: who holds Super Admin, how they verify, and who granted it."""
    roster = []
    grants = {
        grant.subject_id: grant
        for grant in SuperAdminGrant.objects.filter(
            action=GrantAction.GRANT, status=ChangeStatus.APPLIED
        )
        .select_related("proposed_by", "approved_by")
        .order_by("applied_at")
    }
    for admin in User.objects.filter(is_superuser=True, is_active=True).order_by("username"):
        device = TOTPDevice.objects.filter(user=admin, confirmed=True).first()
        grant = grants.get(admin.pk)
        roster.append(
            {
                "user": admin,
                "mfa": "TOTP" if device else None,
                "grant": grant,
                "active_sessions": UserSession.objects.filter(
                    user=admin, revoked_at__isnull=True
                ).count(),
            }
        )
    return roster
