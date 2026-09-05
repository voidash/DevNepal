import typing
import uuid

from django.db import models


class AuditEvent(models.Model):
    """Append-only audit record. Rows are never updated or deleted (ADM-008, SEC-008)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events",
    )
    action = models.CharField(max_length=100, db_index=True)
    content_type = models.ForeignKey(
        "contenttypes.ContentType", null=True, on_delete=models.SET_NULL
    )
    object_id = models.CharField(max_length=255, blank=True, default="")
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    source = models.CharField(max_length=50, default="web")
    result = models.CharField(max_length=20, default="success")
    correlation_id = models.CharField(max_length=100, blank=True, default="", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["-created_at"]
        indexes: typing.ClassVar[list] = [
            models.Index(fields=["content_type", "object_id"]),
            models.Index(fields=["action", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.action} by {self.actor} at {self.created_at:%Y-%m-%d %H:%M}"

    def save(self, *args, **kwargs):
        if self.pk and AuditEvent.objects.filter(pk=self.pk).exists():
            raise PermissionError("AuditEvent rows are immutable (ADM-008)")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):  # pragma: no cover - guarded by tests
        raise PermissionError("AuditEvent rows cannot be deleted (ADM-008)")
