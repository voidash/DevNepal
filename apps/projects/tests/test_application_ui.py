import pytest
from django.test import Client
from django.urls import reverse
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.ministries.tests.factories import MinistryPublisherFactory
from apps.projects.enums import ApplicationStatus, ProjectStatus
from apps.projects.services import apply_to_project, decide_application
from apps.projects.tests.factories import (
    ApplicationFactory,
    SuperAdminFactory,
    UserFactory,
    make_publishable,
)

pytestmark = pytest.mark.django_db


def open_project(**kwargs):
    project = make_publishable(**kwargs)
    project.status = ProjectStatus.OPEN_FOR_CONTRIBUTION
    project.save(update_fields=["status"])
    return project


def ministry_reviewer(project):
    reviewer = UserFactory()
    MinistryPublisherFactory(user=reviewer, ministry=project.ministry)
    return reviewer


def verify_mfa(client, user):
    client.force_login(user)
    setup_url = reverse("accounts:mfa_setup")
    setup = client.get(setup_url)
    assert setup.status_code == 200
    device = TOTPDevice.objects.get(user=user)
    token = totp(
        device.bin_key,
        step=device.step,
        t0=device.t0,
        digits=device.digits,
        drift=device.drift,
    )
    response = client.post(
        setup_url,
        {"token": token},
        HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
    )
    assert response.status_code == 302


@pytest.mark.integration
def test_application_visibility_for_member_reviewer_and_superadmin(client):
    """DSC-008: members, ministry reviewers, and Super Admins can view application records."""
    project = open_project()
    applicant = UserFactory()
    application = apply_to_project(applicant, project, motivation="I can help.")
    unrelated = ApplicationFactory()
    reviewer = ministry_reviewer(project)
    superadmin = SuperAdminFactory()

    client.force_login(applicant)
    response = client.get(reverse("projects:application_list"))
    assert response.status_code == 200
    assert list(response.context["applications"]) == [application]

    for user in (applicant, reviewer, superadmin):
        client.force_login(user)
        listed = client.get(reverse("projects:application_list"))
        detail = client.get(
            reverse("projects:application_detail", kwargs={"application_id": application.pk})
        )
        timeline = client.get(
            reverse("projects:application_timeline", kwargs={"application_id": application.pk})
        )
        assert application in listed.context["applications"]
        assert detail.status_code == 200
        assert timeline.status_code == 200
        assert b"Submitted" in timeline.content

    client.force_login(applicant)
    response = client.get(
        reverse("projects:application_detail", kwargs={"application_id": unrelated.pk})
    )
    assert response.status_code == 404

    client.force_login(reviewer)
    response = client.post(
        reverse("projects:application_withdraw", kwargs={"application_id": application.pk})
    )
    assert response.status_code == 403


@pytest.mark.integration
def test_member_can_withdraw_an_application_from_its_timeline_with_csrf_protection():
    """DSC-007/DSC-008: an applicant can withdraw through the protected timeline UI."""
    project = open_project()
    applicant = UserFactory()
    application = apply_to_project(applicant, project)
    client = Client(enforce_csrf_checks=True)
    client.force_login(applicant)
    timeline_url = reverse(
        "projects:application_timeline", kwargs={"application_id": application.pk}
    )
    withdraw_url = reverse(
        "projects:application_withdraw", kwargs={"application_id": application.pk}
    )

    assert client.post(withdraw_url).status_code == 403
    client.get(timeline_url)
    response = client.post(
        withdraw_url,
        HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
    )

    application.refresh_from_db()
    assert response.status_code == 302
    assert response.url == timeline_url
    assert application.status == ApplicationStatus.WITHDRAWN
    assert application.events.filter(event="withdrawn", actor=applicant).exists()


@pytest.mark.integration
def test_member_can_answer_an_information_request_from_its_timeline(client):
    """DSC-007/DSC-008: an applicant responds to a ministry information request on the timeline."""
    project = open_project()
    applicant = UserFactory()
    application = apply_to_project(applicant, project)
    decide_application(ministry_reviewer(project), application, ApplicationStatus.INFO_REQUESTED)
    client.force_login(applicant)

    response = client.post(
        reverse("projects:application_provide_info", kwargs={"application_id": application.pk}),
        {"text": "My portfolio is https://example.com/member."},
    )

    assert response.status_code == 302
    assert response.url == reverse(
        "projects:application_timeline", kwargs={"application_id": application.pk}
    )
    assert application.events.filter(
        event="info_provided",
        actor=applicant,
        comment="My portfolio is https://example.com/member.",
    ).exists()


@pytest.mark.integration
@pytest.mark.parametrize(
    "decision",
    [
        ApplicationStatus.ACCEPTED,
        ApplicationStatus.WAITLISTED,
        ApplicationStatus.DECLINED,
        ApplicationStatus.INFO_REQUESTED,
    ],
)
def test_authorized_reviewer_can_record_an_available_decision_and_view_history(client, decision):
    """DSC-007/DSC-008: verified owning-ministry reviewers record decisions and see history."""
    project = open_project()
    application = apply_to_project(UserFactory(), project)
    reviewer = ministry_reviewer(project)
    verify_mfa(client, reviewer)
    detail_url = reverse("projects:application_detail", kwargs={"application_id": application.pk})

    detail = client.get(detail_url)
    response = client.post(
        reverse("projects:application_decide", kwargs={"application_id": application.pk}),
        {"decision": decision, "note": "A consistent response."},
    )

    application.refresh_from_db()
    assert detail.status_code == 200
    assert b"Decision" in detail.content
    assert response.status_code == 302
    assert response.url == detail_url
    assert application.status == decision
    assert application.events.filter(to_status=decision, comment="A consistent response.").exists()


@pytest.mark.integration
def test_reviewer_cannot_change_a_terminal_application_decision(client):
    """DSC-007: the decision endpoint preserves terminal application state."""
    project = open_project()
    application = apply_to_project(UserFactory(), project)
    reviewer = ministry_reviewer(project)
    decide_application(reviewer, application, ApplicationStatus.ACCEPTED)
    verify_mfa(client, reviewer)

    response = client.post(
        reverse("projects:application_decide", kwargs={"application_id": application.pk}),
        {"decision": ApplicationStatus.DECLINED},
    )

    application.refresh_from_db()
    assert response.status_code == 400
    assert application.status == ApplicationStatus.ACCEPTED


@pytest.mark.integration
def test_super_admin_can_view_and_record_an_application_decision(client):
    """DSC-007: an MFA-verified Super Admin has the same decision UI and authority."""
    project = open_project()
    application = apply_to_project(UserFactory(), project)
    super_admin = SuperAdminFactory()
    verify_mfa(client, super_admin)
    detail_url = reverse("projects:application_detail", kwargs={"application_id": application.pk})

    detail = client.get(detail_url)
    response = client.post(
        reverse("projects:application_decide", kwargs={"application_id": application.pk}),
        {"decision": ApplicationStatus.ACCEPTED},
    )

    application.refresh_from_db()
    assert detail.status_code == 200
    assert b"Decision" in detail.content
    assert response.status_code == 302
    assert application.status == ApplicationStatus.ACCEPTED


@pytest.mark.integration
def test_application_decision_endpoint_requires_csrf_token():
    """DSC-007: decision submissions reject cross-site requests and accept the rendered token."""
    project = open_project()
    application = apply_to_project(UserFactory(), project)
    reviewer = ministry_reviewer(project)
    client = Client(enforce_csrf_checks=True)
    verify_mfa(client, reviewer)
    detail_url = reverse("projects:application_detail", kwargs={"application_id": application.pk})
    decision_url = reverse("projects:application_decide", kwargs={"application_id": application.pk})

    rejected = client.post(decision_url, {"decision": ApplicationStatus.ACCEPTED})
    client.get(detail_url)
    accepted = client.post(
        decision_url,
        {"decision": ApplicationStatus.ACCEPTED},
        HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
    )

    application.refresh_from_db()
    assert rejected.status_code == 403
    assert accepted.status_code == 302
    assert application.status == ApplicationStatus.ACCEPTED


@pytest.mark.integration
def test_other_ministry_reviewer_cannot_forge_an_application_decision(client):
    """DSC-007: a publisher from another ministry cannot decide an application's outcome."""
    project = open_project()
    application = apply_to_project(UserFactory(), project)
    other_reviewer = UserFactory()
    MinistryPublisherFactory(user=other_reviewer)
    client.force_login(other_reviewer)

    response = client.post(
        reverse("projects:application_decide", kwargs={"application_id": application.pk}),
        {"decision": ApplicationStatus.ACCEPTED},
    )

    application.refresh_from_db()
    assert response.status_code == 404
    assert application.status == ApplicationStatus.SUBMITTED


@pytest.mark.integration
def test_unverified_reviewer_cannot_record_an_application_decision(client):
    """DSC-007/AUTH-005: an owning-ministry publisher needs MFA to decide an application."""
    project = open_project()
    application = apply_to_project(UserFactory(), project)
    reviewer = ministry_reviewer(project)
    client.force_login(reviewer)

    response = client.post(
        reverse("projects:application_decide", kwargs={"application_id": application.pk}),
        {"decision": ApplicationStatus.ACCEPTED},
    )

    application.refresh_from_db()
    assert response.status_code == 403
    assert application.status == ApplicationStatus.SUBMITTED
