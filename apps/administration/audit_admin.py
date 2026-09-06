from django.db import models

from apps.accounts.permissions import is_super_admin
from apps.audit.services import record_audit

REDACTED = "[redacted]"

SENSITIVE_NAME_FRAGMENTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "key",
    "salt",
    "signature",
    "hash",
    "digest",
    "otp",
    "private",
    "session",
    "cookie",
    "nonce",
)

SENSITIVE_FIELD_TYPES = (models.BinaryField, models.FileField)


def _is_sensitive(field) -> bool:
    name = field.name.lower()
    return isinstance(field, SENSITIVE_FIELD_TYPES) or any(
        fragment in name for fragment in SENSITIVE_NAME_FRAGMENTS
    )


def _snapshot(obj):
    """SEC-002/SEC-008: describe a row for the audit trail without copying secrets into it.

    AuditEvent rows are append-only and cannot be deleted through the application,
    so a credential written here would be permanent. Anything whose field name or
    type suggests a secret is recorded as redacted rather than as its value.
    """
    snapshot = {}
    for field in obj._meta.concrete_fields:
        if field.primary_key:
            continue
        snapshot[field.name] = (
            REDACTED if _is_sensitive(field) else str(getattr(obj, field.attname, ""))
        )
    return snapshot


class ReadOnlyModelAdmin:
    """SEC-008: expose a record in model administration without a write path.

    Operational and lifecycle records carry state machines and invariants that
    live in each app's services. Editing them directly here would satisfy the
    audit trail while still bypassing the rules the services enforce, so these
    models are readable in the admin and changed only through their services.
    """

    def has_module_permission(self, request):
        return is_super_admin(request.user)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class AuditedModelAdmin:
    """SEC-008/ADM-008: record every model-administration write in the audit trail.

    Django's admin writes through ``save_model``/``delete_model`` without touching
    ``record_audit``, so a privileged edit made here would otherwise leave no
    trace. Mix this in ahead of ``ModelAdmin`` on every writable reference model.
    """

    def _audit_action(self, verb):
        meta = self.model._meta
        return f"admin.{meta.app_label}.{meta.model_name}.{verb}"

    def has_module_permission(self, request):
        return is_super_admin(request.user)

    def save_model(self, request, obj, form, change):
        before = None
        if change and obj.pk:
            existing = self.model.objects.filter(pk=obj.pk).first()
            before = _snapshot(existing) if existing else None
        super().save_model(request, obj, form, change)
        record_audit(
            actor=request.user,
            action=self._audit_action("change" if change else "add"),
            obj=obj,
            before=before,
            after=_snapshot(obj),
            source="admin",
        )

    def delete_model(self, request, obj):
        before = _snapshot(obj)
        reference = str(obj.pk)
        super().delete_model(request, obj)
        record_audit(
            actor=request.user,
            action=self._audit_action("delete"),
            before=before | {"pk": reference},
            after=None,
            source="admin",
        )

    def delete_queryset(self, request, queryset):
        removed = [_snapshot(obj) | {"pk": str(obj.pk)} for obj in queryset]
        super().delete_queryset(request, queryset)
        for before in removed:
            record_audit(
                actor=request.user,
                action=self._audit_action("delete"),
                before=before,
                after=None,
                source="admin",
            )
