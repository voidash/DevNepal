import json

import pytest
from django.contrib import admin
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, override_settings
from django.urls import reverse

from apps.administration.audit_admin import AuditedModelAdmin
from apps.audit.models import AuditEvent
from apps.audit.tests.factories import UserFactory
from apps.ministries.tests.factories import SuperAdminFactory
from apps.taxonomy.models import Skill

pytestmark = pytest.mark.django_db


@pytest.mark.unit
def test_model_administration_runs_on_the_gated_super_admin_site():
    """SRS:309/SEC-008: /admin is served by the MFA-gated site, not Django's default."""
    resolved = admin.site.site_header

    assert resolved
    assert type(admin.site._wrapped).__name__ == "DevNepalAdminSite"


@override_settings(PRIVILEGED_MFA_BYPASS=True)
@pytest.mark.integration
def test_staff_member_who_is_not_a_super_admin_is_refused(client):
    """SRS:309/SEC-005: is_staff alone no longer opens model administration."""
    staff = UserFactory(is_staff=True)
    client.force_login(staff)

    response = client.get(reverse("admin:index"))

    assert response.status_code == 302
    assert "/admin/login/" in response.url


@override_settings(PRIVILEGED_MFA_BYPASS=False)
@pytest.mark.integration
def test_super_admin_without_verified_mfa_is_refused(client):
    """AUTH-005/SEC-005: model administration requires a verified multi-factor session."""
    super_admin = SuperAdminFactory()
    super_admin.is_verified = lambda: False
    client.force_login(super_admin)

    response = client.get(reverse("admin:index"))

    assert response.status_code == 302
    assert "/admin/login/" in response.url


@override_settings(PRIVILEGED_MFA_BYPASS=True)
@pytest.mark.integration
def test_verified_super_admin_reaches_model_administration(client):
    """ADM-001/SRS:309: an MFA-verified Super Admin maintains reference data."""
    client.force_login(SuperAdminFactory())

    assert client.get(reverse("admin:index")).status_code == 200


@pytest.mark.unit
def test_every_registered_model_admin_either_audits_its_writes_or_forbids_them():
    """SEC-008/ADM-008: no admin surface can change a record without leaving a trace."""

    def is_write_disabled(model_admin):
        request = RequestFactory().get("/admin/")
        request.user = AnonymousUser()
        return not any(
            (
                model_admin.has_add_permission(request),
                model_admin.has_change_permission(request),
                model_admin.has_delete_permission(request),
            )
        )

    unaccounted = [
        f"{model._meta.app_label}.{model._meta.model_name}"
        for model, model_admin in admin.site._registry.items()
        if not isinstance(model_admin, AuditedModelAdmin) and not is_write_disabled(model_admin)
    ]

    assert unaccounted == []


@override_settings(PRIVILEGED_MFA_BYPASS=True)
@pytest.mark.integration
def test_creating_a_record_in_model_administration_is_audited(client):
    """SEC-008/ADM-008: a privileged edit made through /admin leaves an audit record."""
    super_admin = SuperAdminFactory()
    client.force_login(super_admin)

    response = client.post(
        reverse("admin:taxonomy_skill_add"),
        {"name": "Accessibility testing", "slug": "accessibility-testing", "is_active": "on"},
    )

    assert response.status_code == 302
    assert Skill.objects.filter(slug="accessibility-testing").exists()
    event = AuditEvent.objects.get(action="admin.taxonomy.skill.add")
    assert event.actor == super_admin
    assert event.source == "admin"


@override_settings(PRIVILEGED_MFA_BYPASS=True)
@pytest.mark.integration
def test_deleting_a_record_in_model_administration_is_audited(client):
    """SEC-008/ADM-008: deletions through /admin are recorded before the row disappears."""
    skill = Skill.objects.create(name="Retired skill", slug="retired-skill")
    client.force_login(SuperAdminFactory())

    response = client.post(reverse("admin:taxonomy_skill_delete", args=[skill.pk]), {"post": "yes"})

    assert response.status_code == 302
    assert not Skill.objects.filter(pk=skill.pk).exists()
    assert AuditEvent.objects.filter(action="admin.taxonomy.skill.delete").exists()


@pytest.mark.unit
def test_a_snapshot_never_copies_a_credential_into_the_audit_trail():
    """SEC-002/SEC-008: audit rows are permanent, so secrets are redacted before storage."""
    from apps.administration.audit_admin import REDACTED, _snapshot

    user = UserFactory()
    user.set_password("a-real-password")

    snapshot = _snapshot(user)

    assert snapshot["password"] == REDACTED
    assert "a-real-password" not in json.dumps(snapshot)
    assert "pbkdf2" not in json.dumps(snapshot)
    assert snapshot["username"] == user.username


@pytest.mark.unit
def test_a_snapshot_redacts_a_totp_shared_secret():
    """SEC-002/AUTH-005: an MFA shared secret never reaches the audit trail."""
    from django_otp.plugins.otp_totp.models import TOTPDevice

    from apps.administration.audit_admin import REDACTED, _snapshot

    device = TOTPDevice(user=UserFactory(), name="devnepal")

    snapshot = _snapshot(device)

    assert snapshot["key"] == REDACTED
    assert snapshot["name"] == "devnepal"


@override_settings(PRIVILEGED_MFA_BYPASS=True)
@pytest.mark.integration
def test_service_owned_records_have_no_write_path_in_model_administration(client):
    """SEC-008: lifecycle records are readable in the admin but changed only by services."""
    super_admin = SuperAdminFactory()
    client.force_login(super_admin)

    changelist = client.get(reverse("admin:projects_project_changelist"))
    add_page = client.get(reverse("admin:projects_project_add"))

    assert changelist.status_code == 200
    assert add_page.status_code == 403


@override_settings(PRIVILEGED_MFA_BYPASS=True)
@pytest.mark.integration
def test_an_account_cannot_be_edited_through_model_administration(client):
    """SEC-008/AUTH-004: role and suspension changes go through services, not the admin."""
    member = UserFactory()
    client.force_login(SuperAdminFactory())

    response = client.post(
        reverse("admin:accounts_user_change", args=[member.pk]),
        {"username": member.username, "is_superuser": "on"},
    )
    member.refresh_from_db()

    assert response.status_code == 403
    assert member.is_superuser is False
