import typing

from django.contrib.contenttypes.fields import GenericForeignKey
from django.db import models

from apps.moderation.enums import CaseEventType, CaseStatus, ReportReason
from apps.taxonomy.fields import NFCTextField


class Report(models.Model):
    """Structured report on any content object.

    The reporter and evidence are Confidential (SRS 9.2); public moderation
    summaries must never expose them (SRS 13.2, A7).
    """

    reporter = models.ForeignKey(
        "accounts.User",
        null=True,
        on_delete=models.SET_NULL,
        related_name="filed_reports",
    )
    content_type = models.ForeignKey(
        "contenttypes.ContentType",
        on_delete=models.PROTECT,
        related_name="moderation_reports",
    )
    object_id = models.CharField(max_length=255)
    target = GenericForeignKey(ct_field="content_type", fk_field="object_id")
    reason = models.CharField(max_length=25, choices=ReportReason.choices, db_index=True)
    details = NFCTextField(blank=True, default="")
    evidence_url = models.URLField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["-created_at"]
        indexes: typing.ClassVar[list] = [
            models.Index(fields=["content_type", "object_id"], name="idx_report_target"),
            models.Index(fields=["reason", "created_at"], name="idx_report_reason_created"),
        ]

    def __str__(self) -> str:
        return f"{self.get_reason_display()} on {self.target}"


class ModerationCase(models.Model):
    """Queue entry and decision record for one report (ADM-004, ADM-007, BR-010).

    ``security_containment`` marks the BR-010 urgent-security exception: the
    appeal path is not required while it is set. Setting it demands an audited
    reason (see services.enable_security_containment).
    """

    report = models.OneToOneField(Report, on_delete=models.CASCADE, related_name="case")
    assigned_to = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_cases",
    )
    status = models.CharField(
        max_length=16,
        choices=CaseStatus.choices,
        default=CaseStatus.NEW,
        db_index=True,
    )
    action = models.CharField(max_length=25, blank=True, default="")
    action_reason = models.CharField(max_length=25, blank=True, default="")
    enforcement_provenance = models.JSONField(default=dict, blank=True)
    decision_comment = NFCTextField(blank=True, default="")
    decided_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="decided_cases",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    appeal_text = NFCTextField(blank=True, default="")
    appealed_at = models.DateTimeField(null=True, blank=True)
    appeal_status = models.CharField(max_length=10, blank=True, default="")
    appeal_decided_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="appeal_decisions",
    )
    appeal_decided_at = models.DateTimeField(null=True, blank=True)
    security_containment = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["-created_at"]
        verbose_name = "moderation case"
        indexes: typing.ClassVar[list] = [
            models.Index(fields=["status", "-created_at"], name="idx_case_status_created"),
            models.Index(fields=["assigned_to", "status"], name="idx_case_assignee_status"),
        ]

    def __str__(self) -> str:
        return f"Case on {self.report} ({self.get_status_display()})"


class ModerationEvent(models.Model):
    """Append-only moderation case timeline entry (ADM-002, ADM-004, SEC-008)."""

    case = models.ForeignKey(ModerationCase, on_delete=models.PROTECT, related_name="events")
    actor = models.ForeignKey(
        "accounts.User",
        null=True,
        on_delete=models.SET_NULL,
        related_name="moderation_events",
    )
    event = models.CharField(max_length=15, choices=CaseEventType.choices)
    comment = NFCTextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["created_at", "id"]
        indexes: typing.ClassVar[list] = [
            models.Index(fields=["case", "created_at"], name="idx_caseevent_case_created"),
        ]

    def __str__(self) -> str:
        return f"{self.get_event_display()} on {self.case}"

    def save(self, *args, **kwargs):
        if self.pk and ModerationEvent.objects.filter(pk=self.pk).exists():
            raise PermissionError("ModerationEvent rows are append-only (SEC-008)")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("ModerationEvent rows are append-only (SEC-008)")
