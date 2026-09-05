import pytest
from django.test import override_settings

from apps.observability.metrics import HTTP_REQUESTS_TOTAL, HTTP_USER_REQUESTS_TOTAL

pytestmark = [pytest.mark.django_db, pytest.mark.unit]


def test_response_carries_a_correlation_id_header(client):
    """NFR-OBS-01: every response carries a correlation ID."""
    response = client.get("/healthz")
    assert response["X-Correlation-ID"]


def test_untrusted_inbound_correlation_id_is_replaced(client):
    """NFR-OBS-01-U2: public callers cannot choose correlation IDs written to logs or audit rows."""
    response = client.get("/healthz", HTTP_X_CORRELATION_ID="corr-inbound-123")
    assert response["X-Correlation-ID"] != "corr-inbound-123"


@override_settings(OBSERVABILITY_TRUST_INBOUND_CORRELATION_IDS=True)
def test_trusted_inbound_correlation_id_is_echoed_back(client):
    """NFR-OBS-01: a trusted internal proxy can preserve its correlation ID."""
    response = client.get("/healthz", HTTP_X_CORRELATION_ID="corr-inbound-123")
    assert response["X-Correlation-ID"] == "corr-inbound-123"


def test_oversized_inbound_correlation_id_is_replaced(client):
    """NFR-OBS-01: an inbound ID that would overflow the 100-char stored column is rejected."""
    response = client.get("/healthz", HTTP_X_CORRELATION_ID="x" * 200)
    assert response["X-Correlation-ID"] != "x" * 200
    assert len(response["X-Correlation-ID"]) <= 100


def test_request_increments_the_http_requests_total_counter(client):
    """NFR-OBS-01: HTTP RED metrics are recorded per request."""
    before = HTTP_REQUESTS_TOTAL.labels(method="GET", route="healthz", status="200")._value.get()
    client.get("/healthz")
    after = HTTP_REQUESTS_TOTAL.labels(method="GET", route="healthz", status="200")._value.get()
    assert after == before + 1


def test_health_endpoint_is_excluded_from_the_user_facing_sli(client):
    """NFR-AVL-01: probe traffic cannot dilute the public request error-rate SLI."""
    before = sum(
        sample.value for metric in HTTP_USER_REQUESTS_TOTAL.collect() for sample in metric.samples
    )
    client.get("/healthz")
    after = sum(
        sample.value for metric in HTTP_USER_REQUESTS_TOTAL.collect() for sample in metric.samples
    )
    assert after == before


@override_settings(OBSERVABILITY_METRICS_TOKEN="")
def test_metrics_endpoint_denies_requests_when_no_token_is_configured(client):
    """NFR-OBS-01: /metrics fails closed rather than exposing route/error inventory publicly."""
    response = client.get("/metrics")
    assert response.status_code == 403


@override_settings(OBSERVABILITY_METRICS_TOKEN="expected-token")
def test_metrics_endpoint_rejects_the_wrong_token(client):
    """NFR-OBS-01: /metrics rejects a bearer token that does not match."""
    response = client.get("/metrics", HTTP_AUTHORIZATION="Bearer wrong-token")
    assert response.status_code == 403


@override_settings(OBSERVABILITY_METRICS_TOKEN="expected-token")
def test_metrics_endpoint_serves_prometheus_exposition_with_the_right_token(client):
    """NFR-OBS-01: /metrics exposes the request/job/queue series that back the dashboards."""
    response = client.get("/metrics", HTTP_AUTHORIZATION="Bearer expected-token")
    assert response.status_code == 200
    body = response.content.decode()
    assert "http_requests_total" in body
    assert "http_user_requests_total" in body
    assert "background_job_seconds_since_last_success" in body
    assert "queue_depth" in body
    assert "db_queries_total" in body
    assert "db_query_duration_seconds" in body
    assert "db_pending_migrations" in body
