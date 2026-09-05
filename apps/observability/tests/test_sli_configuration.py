from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).parents[3]


def test_alerts_use_the_user_facing_request_sli():
    """NFR-AVL-01: synthetic health and scrape traffic cannot mask public request failures."""
    alerts = (ROOT / "ops" / "observability" / "prometheus" / "alerts.yml").read_text()
    assert "http_user_requests_total" in alerts
    assert 'http_requests_total{status=~"5.."}' not in alerts


def test_availability_dashboards_use_the_user_facing_request_sli():
    """NFR-AVL-01: availability dashboards use the same public-traffic numerator and denominator."""
    dashboards = ROOT / "ops" / "observability" / "grafana" / "dashboards"
    for name in ("availability.json", "executive-overview.json", "http-red.json"):
        assert "http_user_requests_total" in (dashboards / name).read_text()
