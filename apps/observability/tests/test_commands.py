import datetime
import logging

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.observability.commands import InstrumentedCommand
from apps.observability.context import get_correlation_id, reset_correlation_id
from apps.observability.models import JobErrorCode, JobRun, JobStatus
from apps.observability.services import purge_job_runs

pytestmark = [pytest.mark.django_db, pytest.mark.unit]


class _SucceedingCommand(InstrumentedCommand):
    def handle(self, *args, **options):
        return None


class _FailingCommand(InstrumentedCommand):
    def handle(self, *args, **options):
        raise RuntimeError("boom")


class _FailingWithSecretCommand(InstrumentedCommand):
    def handle(self, *args, **options):
        raise RuntimeError("upstream call failed with token=ghp_abcdefghijklmnopqrstuvwx0123")


@pytest.fixture(autouse=True)
def _clean_context():
    reset_correlation_id()
    yield
    reset_correlation_id()


def test_successful_run_records_a_job_run_with_a_correlation_id():
    """NFR-OBS-01: every background job run gets its own correlation ID and JobRun record."""
    call_command(_SucceedingCommand())

    job_run = JobRun.objects.get(command="test_commands")
    assert job_run.status == JobStatus.SUCCESS
    assert job_run.correlation_id
    assert job_run.finished_at is not None


def test_failing_run_is_recorded_as_failed_and_the_exception_propagates():
    """NFR-AVL-02: a failed background job is visible for worker-monitoring dashboards."""
    with pytest.raises(RuntimeError):
        call_command(_FailingCommand())

    job_run = JobRun.objects.get(command="test_commands")
    assert job_run.status == JobStatus.FAILED
    assert job_run.error_code == JobErrorCode.UNEXPECTED
    assert job_run.error == "background job failed: unexpected_error"


def test_correlation_id_is_ambient_during_the_job_and_reset_afterward():
    """NFR-OBS-01-U1: a background job's correlation ID is available to code it calls."""
    seen = {}

    class _ObservingCommand(InstrumentedCommand):
        def handle(self, *args, **options):
            seen["correlation_id"] = get_correlation_id()

    call_command(_ObservingCommand())

    job_run = JobRun.objects.get(command="test_commands")
    assert seen["correlation_id"] == job_run.correlation_id


def test_failed_run_error_is_allowlisted_before_it_is_stored():
    """NFR-OBS-01-U2: job history retains a bounded error code, never exception text or secrets."""
    with pytest.raises(RuntimeError):
        call_command(_FailingWithSecretCommand())

    job_run = JobRun.objects.get(command="test_commands")
    assert "ghp_" not in job_run.error
    assert "upstream" not in job_run.error
    assert job_run.error_code == JobErrorCode.UNEXPECTED


def test_call_command_entry_point_still_works():
    """NFR-MNT-01: instrumentation is transparent to Django's normal command invocation."""
    call_command(_SucceedingCommand())
    assert JobRun.objects.filter(command="test_commands", status=JobStatus.SUCCESS).exists()


def test_successful_job_emits_a_completed_trace_span(caplog):
    """NFR-OBS-01: every instrumented background job emits a safe completed trace span."""
    caplog.set_level(logging.INFO, logger="apps.observability.tracing")

    call_command(_SucceedingCommand())

    span_record = next(record for record in caplog.records if record.msg == "trace.completed")
    assert span_record.span_name == "management_command.test_commands"
    assert span_record.span_status == "unset"


def test_purge_job_runs_removes_only_expired_terminal_rows():
    """NFR-MNT-01: bounded job history retains recent and in-progress operational evidence."""
    old_success = JobRun.objects.create(
        command="old-success",
        correlation_id="old-success",
        status=JobStatus.SUCCESS,
    )
    old_success.started_at = timezone.now() - datetime.timedelta(days=31)
    old_success.save(update_fields=["started_at"])
    old_running = JobRun.objects.create(
        command="old-running",
        correlation_id="old-running",
        status=JobStatus.RUNNING,
    )
    old_running.started_at = timezone.now() - datetime.timedelta(days=31)
    old_running.save(update_fields=["started_at"])
    recent = JobRun.objects.create(
        command="recent", correlation_id="recent", status=JobStatus.SUCCESS
    )

    assert purge_job_runs(retention_days=30) == 1
    assert not JobRun.objects.filter(pk=old_success.pk).exists()
    assert JobRun.objects.filter(pk=old_running.pk).exists()
    assert JobRun.objects.filter(pk=recent.pk).exists()


def test_purge_job_runs_rejects_an_invalid_retention_window():
    """NFR-MNT-01: retention cannot be disabled accidentally by a non-positive setting."""
    with pytest.raises(ValueError):
        purge_job_runs(retention_days=0)
