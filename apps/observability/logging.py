import json
import logging

from apps.observability.context import get_correlation_id
from apps.observability.scrub import scrub_secrets

SAFE_EXTRA_FIELDS = frozenset(
    {
        "command",
        "duration_seconds",
        "error_code",
        "http_method",
        "http_route",
        "http_status",
        "parent_span_id",
        "span_id",
        "span_name",
        "span_status",
        "trace_id",
    }
)


class CorrelationIdFilter(logging.Filter):
    """Attach the ambient correlation ID to every log record (NFR-OBS-01)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id()
        from apps.observability.tracing import current_trace_fields

        for field, value in current_trace_fields().items():
            if not getattr(record, field, None):
                setattr(record, field, value)
        return True


class SecretScrubbingFilter(logging.Filter):
    """Redact token/secret-shaped text from log messages before formatting."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = scrub_secrets(str(record.getMessage()))
        record.args = ()
        for field in SAFE_EXTRA_FIELDS:
            value = getattr(record, field, None)
            if isinstance(value, str):
                setattr(record, field, scrub_secrets(value)[:255])
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", "-"),
        }
        if record.exc_info:
            payload["exception"] = scrub_secrets(self.formatException(record.exc_info))
        payload["message"] = scrub_secrets(payload["message"])
        for field in SAFE_EXTRA_FIELDS:
            value = getattr(record, field, None)
            if isinstance(value, (str, int, float, bool)):
                payload[field] = scrub_secrets(value)[:255] if isinstance(value, str) else value
        return json.dumps(payload)
