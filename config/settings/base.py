"""Base settings shared by all environments."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "django-insecure-dev-key-do-not-use-in-production")

DEBUG = False

ALLOWED_HOSTS: list[str] = []

INSTALLED_APPS = [
    "apps.administration.admin_config.DevNepalAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.accounts",
    "apps.administration",
    "apps.audit",
    "apps.ministries",
    "apps.taxonomy",
    "apps.projects",
    "apps.contributions",
    "apps.github_sync",
    "apps.blogs",
    "apps.recognition",
    "apps.notifications",
    "apps.moderation",
    "apps.analytics",
    "apps.observability",
    "django_otp",
    "django_otp.plugins.otp_totp",
]

MIDDLEWARE = [
    "apps.observability.middleware.CorrelationIdMiddleware",
    "apps.observability.middleware.DatabaseMetricsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "apps.accounts.middleware.SessionSecurityMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.administration.context_processors.roles",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

if os.environ.get("POSTGRES_HOST"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("POSTGRES_DB", "devnepal"),
            "USER": os.environ.get("POSTGRES_USER", "devnepal"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
            "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        },
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        },
    }

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en"

LANGUAGES = [
    ("en", "English"),
    ("ne", "नेपाली"),
]

TIME_ZONE = "Asia/Kathmandu"

USE_I18N = True

USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]

LOCALE_PATHS = [BASE_DIR / "locale"]

DEFAULT_RESPONSE_SLA_DAYS = 5
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024

GITHUB_WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
GITHUB_TOKEN_PURGE = os.environ.get("GITHUB_TOKEN_PURGE") or None
RECOGNITION_ENABLED = False

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.console.EmailBackend",
    },
}

OBSERVABILITY_METRICS_TOKEN = os.environ.get("OBSERVABILITY_METRICS_TOKEN", "")
OBSERVABILITY_TRUST_INBOUND_CORRELATION_IDS = (
    os.environ.get("OBSERVABILITY_TRUST_INBOUND_CORRELATION_IDS", "").lower() == "true"
)
OBSERVABILITY_JOB_RUN_RETENTION_DAYS = int(
    os.environ.get("OBSERVABILITY_JOB_RUN_RETENTION_DAYS", "30")
)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "correlation_id": {"()": "apps.observability.logging.CorrelationIdFilter"},
        "scrub_secrets": {"()": "apps.observability.logging.SecretScrubbingFilter"},
    },
    "formatters": {
        "json": {"()": "apps.observability.logging.JsonFormatter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "filters": ["scrub_secrets", "correlation_id"],
        },
    },
    "root": {
        "handlers": ["console"],
        "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO"),
    },
    "loggers": {
        "django.security": {"level": "WARNING", "propagate": True},
        "django.server": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
