"""Development settings."""

from .base import *

DEBUG = True

TUNNEL_HOST = "devnepal.thapa-ashish.com.np"

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver", "host.docker.internal", TUNNEL_HOST]

CSRF_TRUSTED_ORIGINS = [f"https://{TUNNEL_HOST}"]

PRIVILEGED_MFA_BYPASS = True
