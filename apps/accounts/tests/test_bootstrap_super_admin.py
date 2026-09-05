import io
import re

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.accounts.models import User
from apps.accounts.tests.factories import UserFactory
from apps.audit.models import AuditEvent

pytestmark = pytest.mark.django_db


def run_command(**options):
    stdout = io.StringIO()
    call_command("bootstrap_super_admin", stdout=stdout, **options)
    return stdout.getvalue()


@pytest.mark.unit
def test_auth003_bootstraps_first_superuser_with_generated_password_and_audit():
    """AUTH-003: a fresh deployment provisions the first Super Admin with a one-time
    generated password and an immutable audit event."""
    output = run_command(username="root-admin")

    user = User.objects.get(username="root-admin")
    assert user.is_superuser is True
    assert user.is_staff is True
    assert user.is_active is True

    match = re.search(r"generated-password: (\S+)", output)
    assert match
    assert user.check_password(match.group(1))

    event = AuditEvent.objects.get(action="auth.super_admin_bootstrap")
    assert event.actor == user
    assert event.object_id == str(user.pk)
    assert event.result == "success"
    assert event.after == {"username": "root-admin"}


@pytest.mark.unit
def test_auth003_refuses_when_a_superuser_already_exists():
    """AUTH-003: bootstrap is refused once any Super Admin exists; nothing is created."""
    UserFactory(is_superuser=True, is_staff=True)

    with pytest.raises(CommandError):
        run_command(username="second-root")

    assert not User.objects.filter(username="second-root").exists()
    assert User.objects.count() == 1
    assert not AuditEvent.objects.filter(action="auth.super_admin_bootstrap").exists()


@pytest.mark.unit
def test_auth003_accepts_explicit_password_for_local_development():
    """AUTH-003: --password provisions a known-credential Super Admin for dev environments."""
    output = run_command(username="devroot", password="dev-console-pass-2026")

    user = User.objects.get(username="devroot")
    assert user.is_superuser is True
    assert user.check_password("dev-console-pass-2026")
    assert "generated-password" not in output
    assert AuditEvent.objects.filter(action="auth.super_admin_bootstrap", actor=user).exists()


@pytest.mark.unit
def test_auth003_refuses_an_invalid_username_without_creating_anything():
    """AUTH-003: an invalid username is refused with a typed error before any state changes."""
    with pytest.raises(CommandError):
        run_command(username="bad username!")

    assert User.objects.count() == 0
    assert not AuditEvent.objects.exists()
