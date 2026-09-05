from datetime import timedelta

from django.conf import settings
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.utils import timezone

from apps.accounts.models import UserSession


class SessionSecurityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and request.session.session_key:
            session = UserSession.objects.filter(session_key=request.session.session_key).first()
            if session and (session.revoked_at or self._is_expired(session)):
                logout(request)
                return redirect("accounts:login")
            if session:
                session.last_activity = timezone.now()
                session.save(update_fields=["last_activity"])
        return self.get_response(request)

    @staticmethod
    def _is_expired(session: UserSession) -> bool:
        timeout = getattr(settings, "SESSION_IDLE_TIMEOUT_SECONDS", 1800)
        return bool(
            session.last_activity
            and session.last_activity < timezone.now() - timedelta(seconds=timeout)
        )
