"""Development settings."""

import os

from .base import *

DEBUG = True

TUNNEL_HOST = os.environ.get("DEVNEPAL_TUNNEL_HOST", "devnepal.zapper.cloud")

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver", "host.docker.internal", TUNNEL_HOST]

CSRF_TRUSTED_ORIGINS = [f"https://{TUNNEL_HOST}"]

PRIVILEGED_MFA_BYPASS = True
