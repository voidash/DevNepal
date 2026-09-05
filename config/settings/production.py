"""Production settings for the public DevNepal deployment."""

import os

from .base import *
from .base import BASE_DIR


def _csv_setting(name: str, default: str = "") -> list[str]:
    """Parse a comma-separated environment setting without accepting empty entries."""
    return [value.strip() for value in os.environ.get(name, default).split(",") if value.strip()]


DEBUG = False

ALLOWED_HOSTS = _csv_setting("DJANGO_ALLOWED_HOSTS", "zapper.cloud,www.zapper.cloud")
CSRF_TRUSTED_ORIGINS = _csv_setting(
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    "https://zapper.cloud,https://www.zapper.cloud",
)

STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_ROOT = BASE_DIR / "media"

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_SECURE_HSTS_SECONDS", "3600"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

DEFAULT_FROM_EMAIL = os.environ.get("DJANGO_DEFAULT_FROM_EMAIL", "DevNepal <noreply@zapper.cloud>")
MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
        "OPTIONS": {
            "host": os.environ.get("DJANGO_EMAIL_HOST", "localhost"),
            "port": int(os.environ.get("DJANGO_EMAIL_PORT", "25")),
            "username": os.environ.get("DJANGO_EMAIL_HOST_USER", ""),
            "password": os.environ.get("DJANGO_EMAIL_HOST_PASSWORD", ""),
            "use_tls": os.environ.get("DJANGO_EMAIL_USE_TLS", "true").lower() == "true",
        },
    },
}

PRIVILEGED_MFA_BYPASS = False
