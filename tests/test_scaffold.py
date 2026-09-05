"""Scaffold sanity: the swarm contract depends on these invariants."""

import pytest
from django.apps import apps
from django.conf import settings

EXPECTED_APPS = [
    "accounts",
    "audit",
    "blogs",
    "contributions",
    "github_sync",
    "ministries",
    "moderation",
    "notifications",
    "projects",
    "recognition",
    "taxonomy",
]


@pytest.mark.unit
def test_all_domain_apps_registered():
    """SCAFFOLD: all eleven domain apps are installed."""
    labels = {cfg.label for cfg in apps.get_app_configs()}
    for expected in EXPECTED_APPS:
        assert expected in labels


@pytest.mark.unit
def test_custom_user_is_active():
    """SCAFFOLD: AUTH_USER_MODEL points at accounts.User (AUTH-003 role model depends on it)."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    assert User.__name__ == "User"
    assert User._meta.app_label == "accounts"


@pytest.mark.unit
def test_bilingual_locale_config():
    """SCAFFOLD: NFR-I18N-01 English + Nepali, Asia/Kathmandu rendering timezone."""
    assert set(dict(settings.LANGUAGES)) == {"en", "ne"}
    assert settings.TIME_ZONE == "Asia/Kathmandu"
