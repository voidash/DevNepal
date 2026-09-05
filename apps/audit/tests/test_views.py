import datetime
from unittest import mock

import pytest
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.audit.models import AuditEvent
from apps.audit.tests.factories import AuditEventFactory, UserFactory
from apps.ministries.tests.factories import SuperAdminFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def audit_urlconf():
    with override_settings(ROOT_URLCONF="apps.audit.tests.urls"):
        yield


def verify_mfa(client, user):
    client.force_login(user)
    setup_url = reverse("accounts:mfa_setup")
    client.get(setup_url)
    device = TOTPDevice.objects.get(user=user)
    token = totp(
        device.bin_key,
        step=device.step,
        t0=device.t0,
        digits=device.digits,
        drift=device.drift,
    )
    response = client.post(setup_url, {"token": token})
    assert response.status_code == 302


def event_at(moment, **kwargs):
    with mock.patch("django.utils.timezone.now", return_value=moment):
        return AuditEventFactory(**kwargs)


def seeded_events():
    viewer = UserFactory(username="viewer")
    start = timezone.now() - datetime.timedelta(hours=1)
    for offset, action in enumerate(["audit.oldest", "audit.middle", "audit.newest"]):
        event_at(
            start + datetime.timedelta(minutes=offset),
            actor=viewer,
            action=action,
            correlation_id=f"corr-{offset}",
        )
    return viewer


@pytest.mark.integration
def test_anonymous_user_is_redirected_to_login(client):
    """ADM-008: the audit log is not reachable without authentication."""
    response = client.get(reverse("audit:audit_log"))

    assert response.status_code == 302
    assert reverse("accounts:login") in response.url


@pytest.mark.integration
def test_non_superadmin_receives_403(client):
    """ADM-008/SEC-008: authenticated non-superadmins are denied the audit log."""
    member = UserFactory()
    client.force_login(member)

    response = client.get(reverse("audit:audit_log"))

    assert response.status_code == 403


@pytest.mark.integration
def test_unverified_super_admin_is_redirected_to_mfa(client):
    """ADM-008/AUTH-005: Super Admin audit access requires a verified MFA session."""
    super_admin = SuperAdminFactory()
    super_admin.otp_device = None
    super_admin.is_verified = lambda: False
    client.force_login(super_admin)

    response = client.get(reverse("audit:audit_log"))

    assert response.status_code == 302
    assert response.url == reverse("accounts:mfa_setup")


@pytest.mark.integration
def test_verified_super_admin_sees_dense_newest_first_log(client):
    """SEC-008: the log shows time, actor, action, object, result and correlation id."""
    super_admin = SuperAdminFactory()
    seeded_events()
    verify_mfa(client, super_admin)

    response = client.get(reverse("audit:audit_log"))

    content = response.content.decode()
    page = response.context["events"]
    assert response.status_code == 200
    assert [event.action for event in page] == ["audit.newest", "audit.middle", "audit.oldest"]
    assert page.paginator.count == 3
    assert "<table" in content
    assert "audit.newest" in content
    assert "viewer" in content
    assert "corr-2" in content
    assert 'role="status"' in content


@pytest.mark.integration
def test_action_prefix_actor_and_result_filters_are_allowlisted_and_effective(client):
    """ADM-008: only the allowlisted action-prefix, actor and result filters narrow the log."""
    super_admin = SuperAdminFactory()
    viewer = UserFactory(username="viewer")
    other = UserFactory(username="other")
    start = timezone.now() - datetime.timedelta(hours=1)
    event_at(
        start + datetime.timedelta(minutes=1),
        actor=viewer,
        action="project.publish",
        result="success",
        object_id="abc-1",
    )
    event_at(
        start + datetime.timedelta(minutes=2),
        actor=viewer,
        action="project.delete",
        result="failure",
        object_id="abc-2",
    )
    event_at(
        start + datetime.timedelta(minutes=3),
        actor=other,
        action="role.grant.super_admin",
        result="denied",
        object_id="xyz-9",
    )
    verify_mfa(client, super_admin)

    prefix_page = client.get(reverse("audit:audit_log"), {"action": "project."})
    actor_page = client.get(reverse("audit:audit_log"), {"actor": str(viewer.pk)})
    result_page = client.get(reverse("audit:audit_log"), {"result": "denied"})
    combined = client.get(reverse("audit:audit_log"), {"action": "project.", "result": "failure"})
    hostile = client.get(
        reverse("audit:audit_log"),
        {"action": "pro; DROP", "actor": "not-a-user", "result": "hacked"},
    )

    assert [event.action for event in prefix_page.context["events"]] == [
        "project.delete",
        "project.publish",
    ]
    assert {event.actor.username for event in actor_page.context["events"]} == {"viewer"}
    assert [event.action for event in result_page.context["events"]] == ["role.grant.super_admin"]
    assert [event.action for event in combined.context["events"]] == ["project.delete"]
    assert hostile.status_code == 200
    assert hostile.context["filters"] == {"action": "", "actor": "", "result": "", "q": ""}
    assert hostile.context["events"].paginator.count == 3


@pytest.mark.integration
def test_q_search_matches_action_or_object(client):
    """SEC-008: the q search finds events by action text or object reference."""
    super_admin = SuperAdminFactory()
    start = timezone.now() - datetime.timedelta(hours=1)
    event_at(start, action="project.review.approve", object_id="")
    event_at(start + datetime.timedelta(minutes=1), action="user.suspend", object_id="42af9c")
    verify_mfa(client, super_admin)

    by_action = client.get(reverse("audit:audit_log"), {"q": "review"})
    by_object = client.get(reverse("audit:audit_log"), {"q": "42af9c"})
    by_nothing = client.get(reverse("audit:audit_log"), {"q": "absent-value"})

    assert [event.action for event in by_action.context["events"]] == ["project.review.approve"]
    assert [event.object_id for event in by_object.context["events"]] == ["42af9c"]
    assert by_nothing.context["events"].paginator.count == 0
    assert "No audit events match" in by_nothing.content.decode()


@pytest.mark.integration
def test_pagination_is_bounded_at_25_with_constant_query_count(client):
    """ADM-008: 25 rows per page, newest-first split across pages, no N+1 rendering."""
    super_admin = SuperAdminFactory()
    viewer = UserFactory()
    start = timezone.now() - datetime.timedelta(hours=1)
    for offset in range(26):
        event_at(
            start + datetime.timedelta(seconds=offset), actor=viewer, action=f"batch.{offset:02d}"
        )
    verify_mfa(client, super_admin)

    with CaptureQueriesContext(connection) as queries:
        first_page = client.get(reverse("audit:audit_log"))
    second_page = client.get(reverse("audit:audit_log"), {"page": "2"})
    beyond = client.get(reverse("audit:audit_log"), {"page": "99"})

    content = first_page.content.decode()
    assert first_page.status_code == 200
    assert len(first_page.context["events"]) == 25
    assert first_page.context["events"][0].action == "batch.25"
    assert [event.action for event in second_page.context["events"]] == ["batch.00"]
    assert beyond.context["events"].number == 2
    assert len(queries) <= 6
    assert 'aria-label="Audit log pages"' in content
    assert 'aria-current="page"' in content


@pytest.mark.integration
def test_audit_log_offers_no_mutation_or_export_surface(client):
    """ADM-008/ADM-005: the log view is GET-only and offers no export until purpose-limited."""
    super_admin = SuperAdminFactory()
    event_at(timezone.now(), action="project.publish")
    verify_mfa(client, super_admin)

    post = client.post(reverse("audit:audit_log"), {"action": "tamper"})
    delete_attempt = client.post(reverse("audit:audit_log"), {"result": "failure"})

    assert post.status_code == 405
    assert delete_attempt.status_code == 405
    assert AuditEvent.objects.count() == 1
    with pytest.raises(NoReverseMatch):
        reverse("audit:export")
