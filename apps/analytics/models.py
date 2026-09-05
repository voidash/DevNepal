import typing
import uuid

from django.db import models

from apps.analytics.enums import EventName


class AnalyticsEventRecord(models.Model):
    """ANL-001: privacy-minimized event used only for aggregate reporting."""

    event_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    event_name = models.CharField(max_length=32, choices=EventName.choices, db_index=True)
    ministry = models.ForeignKey(
        "ministries.MinistryOrganization",
        on_delete=models.PROTECT,
        related_name="analytics_events",
    )
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.PROTECT,
        related_name="analytics_events",
    )
    occurred_at = models.DateTimeField(db_index=True)
    source_ref = models.CharField(max_length=120, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["-occurred_at", "-id"]
        constraints: typing.ClassVar[list] = [
            models.CheckConstraint(
                condition=models.Q(event_name__in=EventName.values),
                name="analytics_event_name_documented",
            ),
            models.UniqueConstraint(
                fields=["source_ref"],
                condition=models.Q(source_ref__gt=""),
                name="uniq_analytics_source_ref",
            ),
        ]
        indexes: typing.ClassVar[list] = [
            models.Index(fields=["ministry", "occurred_at"], name="idx_analytics_ministry_month"),
            models.Index(fields=["project", "occurred_at"], name="idx_analytics_project_month"),
        ]
        verbose_name = "analytics event"

    def __str__(self) -> str:
        return f"{self.event_name} for project {self.project_id} at {self.occurred_at.isoformat()}"
