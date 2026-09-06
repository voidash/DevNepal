import typing

from django.db import models
from django.utils import timezone


class JobStatus(models.TextChoices):
    RUNNING = "running", "Running"
    SUCCESS = "success", "Success"
    FAILED = "failed", "Failed"


class JobErrorCode(models.TextChoices):
    COMMAND = "command_error", "Command error"
    CONNECTION = "connection_error", "Connection error"
    DATABASE = "database_error", "Database error"
    TIMEOUT = "timeout", "Timeout"
    UNEXPECTED = "unexpected_error", "Unexpected error"


class JobRun(models.Model):
    """NFR-OBS-01/NFR-AVL-02: one row per background-command execution.

    Cron-style management commands are short-lived processes that exit before
    a pull-based Prometheus scrape could ever see them, so the last-run state
    is persisted here and turned into gauges at scrape time instead.
    """

    command = models.CharField(max_length=100, db_index=True)
    correlation_id = models.CharField(max_length=100, db_index=True)
    status = models.CharField(max_length=20, choices=JobStatus.choices, default=JobStatus.RUNNING)
    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(
        max_length=32, choices=JobErrorCode.choices, blank=True, default=""
    )
    error = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["-started_at"]
        indexes: typing.ClassVar[list] = [
            models.Index(fields=["command", "-started_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.command} [{self.status}] at {self.started_at:%Y-%m-%d %H:%M}"
