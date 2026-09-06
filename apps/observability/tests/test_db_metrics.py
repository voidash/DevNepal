import pytest

from apps.observability.metrics import (
    DB_QUERIES_PER_REQUEST,
    DB_QUERIES_TOTAL,
    _pending_migrations,
)

pytestmark = [pytest.mark.django_db, pytest.mark.unit]


def _counter_total(counter) -> float:
    return sum(sample.value for metric in counter.collect() for sample in metric.samples)


def test_a_request_that_touches_the_database_records_query_metrics(client):
    """NFR-OBS-01: database query count and latency are observable per request."""
    before_queries = _counter_total(DB_QUERIES_TOTAL)
    before_histogram = DB_QUERIES_PER_REQUEST._sum.get()

    response = client.get("/readyz")

    assert response.status_code == 200
    after_queries = _counter_total(DB_QUERIES_TOTAL)
    after_histogram = DB_QUERIES_PER_REQUEST._sum.get()
    assert after_queries > before_queries
    assert after_histogram >= before_histogram


def test_pending_migrations_reports_zero_on_a_fully_migrated_test_database():
    """NFR-OBS-01/maintenance: pending-migration count is a real maintenance signal."""
    assert _pending_migrations() == 0
