import pytest

from apps.observability.context import (
    get_correlation_id,
    is_valid_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean_context():
    reset_correlation_id()
    yield
    reset_correlation_id()


def test_get_correlation_id_mints_one_when_unset():
    """NFR-OBS-01: code running outside a request or job still gets a correlation ID."""
    value = get_correlation_id()
    assert value
    assert get_correlation_id() == value


def test_set_correlation_id_is_observed_by_get_correlation_id():
    """NFR-OBS-01: a request-scoped correlation ID is visible to any code in that request."""
    set_correlation_id("corr-abc123")
    assert get_correlation_id() == "corr-abc123"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("corr-abc123", True),
        ("a" * 100, True),
        ("", False),
        ("a" * 101, False),
        ("has spaces", False),
        ("has/slash", False),
    ],
)
def test_is_valid_correlation_id_matches_the_stored_column_charset(value, expected):
    """NFR-OBS-01: only IDs that fit AuditEvent/ProviderEvent's 100-char column are honored."""
    assert is_valid_correlation_id(value) is expected
