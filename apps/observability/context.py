import re
import uuid
from contextvars import ContextVar

CORRELATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
CORRELATION_ID_HEADER = "HTTP_X_CORRELATION_ID"
CORRELATION_ID_RESPONSE_HEADER = "X-Correlation-ID"

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def new_correlation_id() -> str:
    return uuid.uuid4().hex


def is_valid_correlation_id(value: str) -> bool:
    return bool(CORRELATION_ID_PATTERN.fullmatch(value))


def set_correlation_id(value: str) -> None:
    _correlation_id.set(value)


def get_correlation_id() -> str:
    """NFR-OBS-01: the ambient correlation ID for the current request or job.

    Mints one on first use so code running outside a request (shell, tests
    that skip the middleware) never observes an empty ID.
    """
    value = _correlation_id.get()
    if value is None:
        value = new_correlation_id()
        _correlation_id.set(value)
    return value


def reset_correlation_id() -> None:
    _correlation_id.set(None)
