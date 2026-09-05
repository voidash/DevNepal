import contextlib

from django.db import models

from apps.audit.models import AuditEvent


class AuditBulkMutationError(PermissionError):
    """Queryset-level bulk mutation of AuditEvent rows (ADM-008, SEC-008)."""


class _ImmutableAuditQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise AuditBulkMutationError("AuditEvent bulk update is blocked (ADM-008)")

    def bulk_update(self, objs, fields, **kwargs):
        raise AuditBulkMutationError("AuditEvent bulk update is blocked (ADM-008)")

    def delete(self):
        raise AuditBulkMutationError("AuditEvent bulk delete is blocked (ADM-008)")


class _GuardedAuditManager(models.Manager):
    def get_queryset(self):
        return _ImmutableAuditQuerySet(self.model, using=self._db)


@contextlib.contextmanager
def bulk_update_guard():
    """Swap AuditEvent.objects for a manager whose queryset update/delete raise.

    Use around privileged surfaces (admin views, middleware) so no ORM path can
    bulk-update or bulk-delete audit rows (ADM-008, SEC-008). Creation and reads
    stay available; record_audit keeps working inside the guard.
    """
    original = AuditEvent.objects
    guarded = _GuardedAuditManager()
    guarded.model = AuditEvent
    AuditEvent.objects = guarded
    try:
        yield
    finally:
        AuditEvent.objects = original


def record_audit(
    *,
    actor,
    action: str,
    obj=None,
    before=None,
    after=None,
    source: str = "web",
    result: str = "success",
    correlation_id: str | None = None,
) -> AuditEvent:
    from django.contrib.contenttypes.models import ContentType

    return AuditEvent.objects.create(
        actor=actor,
        action=action,
        content_type=ContentType.objects.get_for_model(obj) if obj is not None else None,
        object_id=str(getattr(obj, "pk", "")) if obj is not None else "",
        before=before,
        after=after,
        source=source,
        result=result,
        correlation_id=correlation_id or "",
    )
