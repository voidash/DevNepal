import pytest
from django.test import Client, override_settings
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.audit.tests.factories import AuditEventFactory, UserFactory
from apps.ministries.tests.factories import SuperAdminFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def audit_urlconf():
    with override_settings(ROOT_URLCONF="apps.audit.tests.urls"):
        yield


@pytest.mark.integration
def test_admin_changelist_is_visible_to_superusers_only(client):
    """ADM-008/SEC-008: the Django admin exposes the audit trail to Super Admins for viewing."""
    super_admin = SuperAdminFactory()
    AuditEventFactory(action="project.publish")
    staff_member = UserFactory(is_staff=True, is_superuser=False)

    superclient = Client()
    superclient.force_login(super_admin)
    changelist = superclient.get(reverse("admin:audit_auditevent_changelist"))
    staffclient = Client()
    staffclient.force_login(staff_member)
    denied = staffclient.get(reverse("admin:audit_auditevent_changelist"))

    content = changelist.content.decode()
    assert changelist.status_code == 200
    assert "project.publish" in content
    assert denied.status_code == 403


@pytest.mark.integration
def test_admin_denies_add_change_and_delete_views(client):
    """ADM-008: no admin path may create, edit or erase an AuditEvent row."""
    super_admin = SuperAdminFactory()
    event = AuditEventFactory(action="project.publish")
    client.force_login(super_admin)
    add_url = reverse("admin:audit_auditevent_add")
    change_url = reverse("admin:audit_auditevent_change", kwargs={"object_id": event.pk})
    delete_url = reverse("admin:audit_auditevent_delete", kwargs={"object_id": event.pk})

    add_post = client.post(add_url, {"action": "tampered"})
    change_get = client.get(change_url)
    change_post = client.post(change_url, {"action": "tampered"})
    delete_get = client.get(delete_url)
    delete_post = client.post(delete_url, {"post": "yes"})

    assert add_post.status_code == 403
    assert change_get.status_code == 200
    assert "_save" not in change_get.content.decode()
    assert change_post.status_code == 403
    assert AuditEvent.objects.get(pk=event.pk).action == "project.publish"
    assert delete_get.status_code == 403
    assert delete_post.status_code == 403
    assert AuditEvent.objects.filter(pk=event.pk).exists()


@pytest.mark.integration
def test_admin_changelist_has_no_delete_action_or_export(client):
    """ADM-008/ADM-005: the changelist exposes no bulk-delete action and no export link."""
    super_admin = SuperAdminFactory()
    event = AuditEventFactory()
    client.force_login(super_admin)

    response = client.post(
        reverse("admin:audit_auditevent_changelist"),
        {"action": "delete_selected", "_selected_action": str(event.pk)},
    )
    changelist = client.get(reverse("admin:audit_auditevent_changelist"))

    content = changelist.content.decode()
    assert response.status_code == 200
    assert AuditEvent.objects.filter(pk=event.pk).exists()
    assert "Export" not in content
    assert "audit:export" not in content
