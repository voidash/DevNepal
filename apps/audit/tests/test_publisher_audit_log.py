import pytest
from django.urls import reverse
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.audit.models import AuditEvent
from apps.audit.publisher_audit import (
    PUBLISHER_EXPORT_LIMIT,
    PublisherAuditExportAuthorizationError,
    export_publisher_audit,
)
from apps.audit.services import record_audit
from apps.audit.tests.factories import AuditEventFactory, UserFactory
from apps.ministries.enums import PublisherStatus
from apps.ministries.tests.factories import (
    MinistryOrganizationFactory,
    MinistryPublisherFactory,
    SuperAdminFactory,
)
from apps.projects.tests.factories import ProjectFactory

pytestmark = pytest.mark.django_db


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


@pytest.mark.integration
def test_my_actions_requires_an_active_mfa_verified_ministry_publisher(client):
    """AUTH-005/SEC-008: only an MFA-verified active publisher can open their audit trail."""
    publisher = MinistryPublisherFactory()
    former_publisher = MinistryPublisherFactory()
    former_publisher.status = PublisherStatus.REVOKED
    former_publisher.save(update_fields=["status"])
    member = UserFactory()

    anonymous = client.get(reverse("audit:my_actions"))
    client.force_login(member)
    member_response = client.get(reverse("audit:my_actions"))
    client.force_login(former_publisher.user)
    former_publisher_response = client.get(reverse("audit:my_actions"))
    client.force_login(publisher.user)
    mfa_response = client.get(reverse("audit:my_actions"))

    assert anonymous.status_code == 302
    assert member_response.status_code == 403
    assert former_publisher_response.status_code == 403
    assert mfa_response.status_code == 302
    assert mfa_response.url == reverse("accounts:mfa_setup")


@pytest.mark.integration
def test_my_actions_defaults_to_personal_append_only_history(client):
    """GOV-005/ADM-008: the default ledger includes only the publisher's own actions."""
    assignment = MinistryPublisherFactory()
    publisher = assignment.user
    colleague = MinistryPublisherFactory(ministry=assignment.ministry).user
    foreign_actor = UserFactory(username="foreign-actor")
    own = AuditEventFactory(
        actor=publisher,
        action="project.draft_created",
        after={"reason": "Pilot"},
    )
    colleague_event = AuditEventFactory(actor=colleague, action="project.submitted")
    foreign_event = AuditEventFactory(actor=foreign_actor, action="project.foreign")
    verify_mfa(client, publisher)

    response = client.get(reverse("audit:my_actions"))

    events = list(response.context["events"])
    content = response.content.decode()
    assert response.status_code == 200
    assert [event.pk for event in events] == [own.pk]
    assert colleague_event.action not in content
    assert foreign_event.action not in content
    assert "Audit log · my actions" in content
    assert "Basis / reason" in content
    assert "Pilot" in content
    assert 'aria-label="Audit scope"' in content


@pytest.mark.integration
def test_organization_scope_is_limited_to_selected_ministry_resources_and_named_officers(client):
    """GOV-005/SEC-008: organization history cannot disclose another ministry's actions or data."""
    ministry = MinistryOrganizationFactory(name_en="Visible Ministry")
    assignment = MinistryPublisherFactory(ministry=ministry)
    colleague_assignment = MinistryPublisherFactory(ministry=ministry)
    foreign_ministry = MinistryOrganizationFactory(name_en="Hidden Ministry")
    foreign_assignment = MinistryPublisherFactory(ministry=foreign_ministry)
    super_admin = SuperAdminFactory()
    visible_project = ProjectFactory(ministry=ministry)
    hidden_project = ProjectFactory(ministry=foreign_ministry)
    own_event = AuditEventFactory(actor=assignment.user, action="account.settings_saved")
    project_event = record_audit(
        actor=colleague_assignment.user,
        action="project.submitted",
        obj=visible_project,
        after={"reason": "Suitability confirmed"},
    )
    officer_event = record_audit(
        actor=super_admin,
        action="publisher.granted",
        obj=colleague_assignment,
        after={"reason": "Nomination accepted"},
    )
    foreign_project_event = record_audit(
        actor=foreign_assignment.user,
        action="project.submitted.hidden",
        obj=hidden_project,
    )
    unrelated_event = AuditEventFactory(actor=foreign_assignment.user, action="account.hidden")
    verify_mfa(client, assignment.user)

    response = client.get(
        reverse("audit:my_actions"),
        {"scope": "organization", "ministry": ministry.pk},
    )

    visible_ids = {event.pk for event in response.context["events"]}
    content = response.content.decode()
    assert response.status_code == 200
    assert {own_event.pk, project_event.pk, officer_event.pk} <= visible_ids
    assert foreign_project_event.pk not in visible_ids
    assert unrelated_event.pk not in visible_ids
    assert "Visible Ministry" in content
    assert "Hidden Ministry" not in content
    assert "Suitability confirmed" in content


@pytest.mark.integration
def test_organization_filters_are_allowlisted_and_keep_the_scope_boundary(client):
    """GOV-005/ADM-008: filters narrow a publisher's selected-ministry audit evidence safely."""
    ministry = MinistryOrganizationFactory()
    assignment = MinistryPublisherFactory(ministry=ministry)
    project = ProjectFactory(ministry=ministry)
    record_audit(actor=assignment.user, action="project.published", obj=project, result="success")
    record_audit(
        actor=assignment.user,
        action="publisher.contact_verified",
        obj=assignment,
        result="failure",
    )
    verify_mfa(client, assignment.user)

    projects = client.get(
        reverse("audit:my_actions"),
        {"scope": "organization", "ministry": ministry.pk, "category": "projects"},
    )
    failures = client.get(
        reverse("audit:my_actions"),
        {"scope": "organization", "ministry": ministry.pk, "result": "failure"},
    )
    hostile = client.get(
        reverse("audit:my_actions"),
        {"scope": "global", "ministry": "999999", "category": "everything", "result": "bad"},
    )

    assert [event.action for event in projects.context["events"]] == ["project.published"]
    assert [event.action for event in failures.context["events"]] == ["publisher.contact_verified"]
    assert hostile.status_code == 200
    assert hostile.context["filters"] == {
        "scope": "mine",
        "ministry": "",
        "category": "all",
        "result": "",
    }


@pytest.mark.integration
def test_publisher_exports_the_scoped_ledger_with_purpose_and_csv_injection_protection(client):
    """GOV-005/ADM-005: C6.2 CSV is bounded, purpose-audited, and spreadsheet-safe."""
    assignment = MinistryPublisherFactory()
    event = AuditEventFactory(
        actor=assignment.user,
        action="project.updated",
        after={"reason": '=HYPERLINK("https://attacker.invalid")'},
    )
    verify_mfa(client, assignment.user)

    response = client.post(
        reverse("audit:export_my_actions"),
        {
            "scope": "mine",
            "category": "all",
            "result": "",
            "purpose": "Quarterly ministry accountability review",
        },
    )

    body = response.content.decode("utf-8-sig")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    assert "project.updated" in body
    assert "'=HYPERLINK" in body
    export_event = AuditEvent.objects.get(action="audit.publisher_export")
    assert export_event.after == {
        "purpose": "Quarterly ministry accountability review",
        "count": 1,
        "scope": "mine",
        "ministry_id": None,
        "category": "all",
        "result": "",
    }
    assert str(event.after) not in str(export_event.after)


@pytest.mark.integration
def test_publisher_export_requires_a_meaningful_purpose_and_is_rate_limited(client):
    """ADM-005/SEC-006: empty-purpose and excessive C6.2 exports fail and are audited."""
    assignment = MinistryPublisherFactory()
    verify_mfa(client, assignment.user)

    purposeless = client.post(
        reverse("audit:export_my_actions"),
        {"scope": "mine", "purpose": "short"},
    )
    for _ in range(PUBLISHER_EXPORT_LIMIT):
        AuditEventFactory(actor=assignment.user, action="audit.publisher_export")
    limited = client.post(
        reverse("audit:export_my_actions"),
        {"scope": "mine", "purpose": "Quarterly ministry accountability review"},
    )

    assert purposeless.status_code == 400
    assert limited.status_code == 429
    assert limited["Retry-After"] == "3600"
    assert AuditEvent.objects.filter(action="audit.publisher_export.denied").count() == 2


@pytest.mark.integration
def test_export_service_rejects_a_ministry_outside_the_publishers_active_scope():
    """GOV-005/SEC-005: direct service callers cannot export another ministry's ledger."""
    assignment = MinistryPublisherFactory()
    foreign_ministry = MinistryOrganizationFactory()

    with pytest.raises(PublisherAuditExportAuthorizationError):
        export_publisher_audit(
            user=assignment.user,
            ministry=foreign_ministry,
            scope="organization",
            category="all",
            result="",
            purpose="Quarterly ministry accountability review",
        )
