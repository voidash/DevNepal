import logging
import time

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError
from django.utils import timezone
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from apps.observability.context import new_correlation_id, reset_correlation_id, set_correlation_id
from apps.observability.metrics import JOB_RUN_DURATION_SECONDS, JOB_RUNS_TOTAL
from apps.observability.models import JobErrorCode, JobRun, JobStatus

logger = logging.getLogger("apps.observability.jobs")


class InstrumentedCommand(BaseCommand):
    """NFR-OBS-01/NFR-AVL-02: give recurring management commands a correlation ID,
    a JobRun row, structured start/finish logs, and Prometheus counters.

    Subclasses are unchanged otherwise — they still implement `handle()`.
    """

    def execute(self, *args, **options):
        command_name = self.__class__.__module__.rsplit(".", 1)[-1]
        correlation_id = new_correlation_id()
        set_correlation_id(correlation_id)
        try:
            tracer = trace.get_tracer("devnepal.jobs")
            with tracer.start_as_current_span(f"management_command.{command_name}") as span:
                job_run = JobRun.objects.create(command=command_name, correlation_id=correlation_id)
                logger.info("job.started", extra={"command": command_name})
                started_at = time.monotonic()
                try:
                    result = super().execute(*args, **options)
                except Exception as exc:
                    error_code = classify_job_error(exc)
                    span.set_status(Status(StatusCode.ERROR, error_code))
                    self._finish(job_run, command_name, started_at, JobStatus.FAILED, error_code)
                    logger.error(
                        "job.failed", extra={"command": command_name, "error_code": error_code}
                    )
                    raise
                else:
                    duration = self._finish(job_run, command_name, started_at, JobStatus.SUCCESS)
                    logger.info(
                        "job.finished",
                        extra={"command": command_name, "duration_seconds": duration},
                    )
                    return result
        finally:
            reset_correlation_id()

    def _finish(self, job_run, command_name, started_at, status, error_code="") -> float:
        duration = time.monotonic() - started_at
        job_run.status = status
        job_run.finished_at = timezone.now()
        job_run.error_code = error_code
        job_run.error = f"background job failed: {error_code}" if error_code else ""
        job_run.save(update_fields=["status", "finished_at", "error_code", "error"])
        JOB_RUNS_TOTAL.labels(command=command_name, status=status).inc()
        JOB_RUN_DURATION_SECONDS.labels(command=command_name).observe(duration)
        return duration


def classify_job_error(exc: Exception) -> JobErrorCode:
    if isinstance(exc, DatabaseError):
        return JobErrorCode.DATABASE
    if isinstance(exc, ConnectionError):
        return JobErrorCode.CONNECTION
    if isinstance(exc, TimeoutError):
        return JobErrorCode.TIMEOUT
    if isinstance(exc, CommandError):
        return JobErrorCode.COMMAND
    return JobErrorCode.UNEXPECTED
