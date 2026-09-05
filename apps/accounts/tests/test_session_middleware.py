from datetime import timedelta

import pytest
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse
from django.test import RequestFactory, override_settings
from django.utils import timezone

from apps.accounts.middleware import SessionSecurityMiddleware
from apps.accounts.models import UserSession
from apps.accounts.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def request_for(user):
    request = RequestFactory().get("/")
    SessionMiddleware(lambda request: HttpResponse()).process_request(request)
    request.session.save()
    request.user = user
    return request


@pytest.mark.unit
def test_revoked_session_is_logged_out_before_the_view_runs():
    """AUTH-007: a revoked session is rejected on its next request."""
    request = request_for(UserFactory())
    UserSession.objects.create(
        user=request.user,
        session_key=request.session.session_key,
        revoked_at=timezone.now(),
    )
    middleware = SessionSecurityMiddleware(lambda request: HttpResponse("view"))

    response = middleware(request)

    assert response.status_code == 302
    assert response.url.endswith("/accounts/login/")


@pytest.mark.unit
@override_settings(SESSION_IDLE_TIMEOUT_SECONDS=60)
def test_idle_session_is_logged_out_before_the_view_runs():
    """AUTH-007: server-side idle expiry rejects a stale authenticated session."""
    request = request_for(UserFactory())
    UserSession.objects.create(
        user=request.user,
        session_key=request.session.session_key,
        last_activity=timezone.now() - timedelta(seconds=61),
    )
    middleware = SessionSecurityMiddleware(lambda request: HttpResponse("view"))

    response = middleware(request)

    assert response.status_code == 302
