import logging

import pytest

pytestmark = [pytest.mark.django_db, pytest.mark.unit]


def test_request_emits_a_w3c_trace_and_a_completed_span(client, caplog):
    """NFR-OBS-01: every request has a trace context and a completed safe span record."""
    caplog.set_level(logging.INFO, logger="apps.observability.tracing")

    response = client.get("/healthz")

    assert response["traceparent"].startswith("00-")
    span_record = next(record for record in caplog.records if record.msg == "trace.completed")
    assert span_record.trace_id
    assert span_record.span_id
    assert span_record.span_name == "http.request"
