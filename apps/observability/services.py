from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.observability.models import JobRun, JobStatus


def purge_job_runs(*, retention_days: int | None = None, now=None) -> int:
    days = (
        retention_days
        if retention_days is not None
        else getattr(settings, "OBSERVABILITY_JOB_RUN_RETENTION_DAYS", 30)
    )
    if days < 1:
        raise ValueError("OBSERVABILITY_JOB_RUN_RETENTION_DAYS must be positive")
    threshold = (now or timezone.now()) - timedelta(days=days)
    deleted, _ = JobRun.objects.filter(
        status__in=(JobStatus.SUCCESS, JobStatus.FAILED), started_at__lt=threshold
    ).delete()
    return deleted
