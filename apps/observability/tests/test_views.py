from unittest import mock

import pytest
from django.db.utils import InterfaceError, OperationalError

pytestmark = [pytest.mark.django_db, pytest.mark.unit]


def test_healthz_reports_ok_without_touching_the_database(client):
    """NFR-AVL-02: liveness succeeds even if a dependency is unhealthy."""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_reports_ready_when_the_database_answers(client):
    """NFR-AVL-02: readiness reports ready once the database is reachable."""
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readyz_reports_unavailable_when_the_database_is_down(client):
    """NFR-AVL-02: readiness fails closed, without leaking the underlying error, on a DB outage."""
    with mock.patch("apps.observability.views.connection") as mock_connection:
        mock_connection.cursor.side_effect = OperationalError("connection refused")
        response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


def test_readyz_reports_unavailable_on_a_dead_connection(client):
    """NFR-AVL-02: InterfaceError is a DatabaseError sibling of OperationalError, not a subclass."""
    with mock.patch("apps.observability.views.connection") as mock_connection:
        mock_connection.cursor.side_effect = InterfaceError("connection already closed")
        response = client.get("/readyz")
    assert response.status_code == 503
