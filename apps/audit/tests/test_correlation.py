import json
import logging

import pytest
from django.core.management import call_command
from django.http import HttpResponse
from django.test import RequestFactory

from apps.audit.models import AuditEvent
from apps.audit.services import record_audit
from apps.observability.commands import InstrumentedCommand
from apps.observability.context import reset_correlation_id
from apps.observability.logging import CorrelationIdFilter, JsonFormatter, SecretScrubbingFilter
from apps.observability.middleware import CorrelationIdMiddleware
from apps.observability.models import JobRun

pytestmark = [pytest.mark.django_db, pytest.mark.unit]


@pytest.fixture(autouse=True)
def _clean_context():
    reset_correlation_id()
    yield
    reset_correlation_id()


def _view_that_records_an_audit_event(request):
    record_audit(actor=None, action="test.correlation.request", result="success")
    return HttpResponse("ok")


def test_request_correlation_id_is_present_on_the_response_and_the_audit_row_it_creates():
    """NFR-OBS-01-U1: correlation ID present on responses and propagated into audit events."""
    middleware = CorrelationIdMiddleware(_view_that_records_an_audit_event)
    response = middleware(RequestFactory().get("/"))

    event = AuditEvent.objects.get(action="test.correlation.request")
    assert response["X-Correlation-ID"]
    assert event.correlation_id == response["X-Correlation-ID"]


def test_background_job_correlation_id_is_propagated_into_audit_events_it_creates():
    """NFR-OBS-01-U1: a background job's correlation ID is propagated into audit events."""

    class _AuditingCommand(InstrumentedCommand):
        def handle(self, *args, **options):
            record_audit(actor=None, action="test.correlation.job", result="success")

    call_command(_AuditingCommand())

    job_run = JobRun.objects.get(command="test_correlation")
    event = AuditEvent.objects.get(action="test.correlation.job")
    assert event.correlation_id == job_run.correlation_id


def test_log_scrubber_removes_token_and_secret_patterns_before_formatting():
    """NFR-OBS-01-U2: log scrubber removes token/secret patterns from emitted log lines."""
    record = logging.LogRecord(
        name="apps.github_sync",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="webhook delivered with token=ghp_abcdefghijklmnopqrstuvwx0123",
        args=(),
        exc_info=None,
    )
    assert SecretScrubbingFilter().filter(record) is True
    assert CorrelationIdFilter().filter(record) is True

    payload = json.loads(JsonFormatter().format(record))
    assert "ghp_" not in payload["message"]
    assert payload["correlation_id"]
