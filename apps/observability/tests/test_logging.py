import json
import logging

import pytest

from apps.observability.logging import CorrelationIdFilter, JsonFormatter, SecretScrubbingFilter

pytestmark = pytest.mark.unit


def test_json_formatter_preserves_allowlisted_structured_extras():
    """NFR-OBS-01: safe job fields remain queryable in structured JSON logs."""
    record = logging.LogRecord(
        name="apps.observability.jobs",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="job.finished",
        args=(),
        exc_info=None,
    )
    record.command = "publish_scheduled"
    record.duration_seconds = 1.25
    record.token = "should-not-be-emitted"
    SecretScrubbingFilter().filter(record)
    CorrelationIdFilter().filter(record)

    payload = json.loads(JsonFormatter().format(record))
    assert payload["command"] == "publish_scheduled"
    assert payload["duration_seconds"] == 1.25
    assert "token" not in payload


def test_django_server_uses_the_scrubbed_json_handler(settings):
    """NFR-OBS-01-U2: Django development request logs use the protected JSON pipeline."""
    logger_config = settings.LOGGING["loggers"]["django.server"]
    assert logger_config["handlers"] == ["console"]
    assert logger_config["propagate"] is False
