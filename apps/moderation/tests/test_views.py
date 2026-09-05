from datetime import timedelta

import pytest
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test import Client, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.ministries.tests.factories import SuperAdminFactory, UserFactory
from apps.moderation.enums import AppealStatus, CaseStatus, ModerationAction, ReportReason
from apps.moderation.models import ModerationCase, Report
from apps.moderation.services import appeal, record_decision
from apps.moderation.tests.factories import ModerationCaseFactory
from apps.projects.tests.factories import ProjectFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def moderation_urlconf():
    with override_settings(ROOT_URLCONF="apps.moderation.tests.urls"):
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


@pytest.mark.integration
def test_authenticated_member_submits_a_report(client):
    """ADM-003: an authenticated member submits a structured report into the case queue."""
    member = UserFactory()
    target = ProjectFactory()
    client.force_login(member)

    response = client.post(
        reverse("moderation:report_create"),
        {
            "content_type": ContentType.objects.get_for_model(target).pk,
            "object_id": target.pk,
            "reason": ReportReason.SPAM,
            "details": "Repeated commercial advertising",
        },
    )

    assert response.status_code == 302
    report = Report.objects.get()
    assert response.url == reverse("moderation:report_confirmation", kwargs={"pk": report.case.pk})
    assert report.reporter == member
    assert report.target == target


@pytest.mark.integration
def test_authenticated_member_reports_profile_impersonation_into_moderation_queue(client):
    """MEM-010/ADM-003: an impersonation report on a member account creates a confidential case."""
    reporter = UserFactory()
    target = UserFactory(username="impersonated-member")
    client.force_login(reporter)

    response = client.post(
        reverse("moderation:report_create"),
        {
            "content_type": ContentType.objects.get_for_model(target).pk,
            "object_id": target.pk,
            "reason": ReportReason.IMPERSONATION,
            "details": "This account is claiming to be another contributor.",
        },
    )

    report = Report.objects.get()
    assert response.status_code == 302
    assert report.target == target
    assert report.reason == ReportReason.IMPERSONATION
    assert report.case.status == CaseStatus.NEW


@pytest.mark.integration
def test_report_form_accepts_prefilled_target_from_public_profile(client):
    """ADM-003/MEM-010: a public-profile report handoff preselects the intended account target."""
    member = UserFactory()
    target = UserFactory(username="reported-member")
    client.force_login(member)

    response = client.get(
        reverse("moderation:report_create"),
        {
            "content_type": ContentType.objects.get_for_model(target).pk,
            "object_id": target.pk,
        },
    )

    assert response.status_code == 200
    assert response.context["form"].initial["content_type"] == str(
        ContentType.objects.get_for_model(target).pk
    )
    assert response.context["form"].initial["object_id"] == str(target.pk)


@pytest.mark.integration
def test_forged_appeal_is_denied_to_non_reporter(client):
    """ADM-007/BR-010: only the case reporter can file its appeal."""
    reporter = UserFactory()
    case = ModerationCaseFactory(status=CaseStatus.UNDER_REVIEW, report__reporter=reporter)
    record_decision(SuperAdminFactory(), case, ModerationAction.WARNING, ReportReason.SPAM)
    client.force_login(UserFactory())

    response = client.post(
        reverse("moderation:appeal", kwargs={"pk": case.pk}), {"grounds": "forged"}
    )

    assert response.status_code == 403
    case.refresh_from_db()
    assert case.appeal_status == ""


@pytest.mark.integration
def test_unverified_super_admin_cannot_access_case_queue(client):
    """AUTH-005/ADM-002: Super Admin queue access requires a verified MFA session."""
    super_admin = SuperAdminFactory()
    super_admin.otp_device = None
    super_admin.is_verified = lambda: False
    client.force_login(super_admin)

    response = client.get(reverse("moderation:case_queue"))

    assert response.status_code == 302
    assert response.url == reverse("accounts:mfa_setup")


@pytest.mark.integration
def test_case_queue_paginates_filtered_cases_with_safe_ordering(client):
    """ADM-002: the confidential queue has bounded, isolated, safely filtered pages."""
    super_admin = SuperAdminFactory()
    cases = [
        ModerationCaseFactory(
            status=CaseStatus.UNDER_REVIEW,
            report__reason=ReportReason.HARASSMENT,
        )
        for _ in range(27)
    ]
    ModerationCaseFactory(status=CaseStatus.NEW, report__reason=ReportReason.HARASSMENT)
    ModerationCaseFactory(status=CaseStatus.UNDER_REVIEW, report__reason=ReportReason.SPAM)
    verify_mfa(client, super_admin)

    first_page = client.get(
        reverse("moderation:case_queue"),
        {
            "status": CaseStatus.UNDER_REVIEW,
            "reason": ReportReason.HARASSMENT,
            "order": "oldest",
        },
    )
    second_page = client.get(
        reverse("moderation:case_queue"),
        {
            "status": CaseStatus.UNDER_REVIEW,
            "reason": ReportReason.HARASSMENT,
            "order": "oldest",
            "page": 2,
        },
    )
    invalid_inputs = client.get(
        reverse("moderation:case_queue"),
        {"status": "not-a-status", "reason": "not-a-reason", "order": "reporter__username"},
    )

    first_cases = list(first_page.context["cases"])
    second_cases = list(second_page.context["cases"])
    assert first_page.status_code == 200
    assert len(first_cases) == 25
    assert {case.pk for case in first_cases}.isdisjoint(case.pk for case in second_cases)
    assert {case.pk for case in first_cases + second_cases} == {case.pk for case in cases}
    assert first_page.context["filters"] == {
        "status": CaseStatus.UNDER_REVIEW,
        "reason": ReportReason.HARASSMENT,
        "order": "oldest",
    }
    assert invalid_inputs.context["filters"] == {"status": "", "reason": "", "order": "newest"}
    assert "status=under_review" in first_page.content.decode()
    assert "reason=harassment" in first_page.content.decode()
    assert "order=oldest" in first_page.content.decode()


@pytest.mark.integration
def test_case_queue_has_constant_query_count_and_accessible_pagination(client):
    """ADM-002/NFR-A11Y-01: paginating the queue prevents N+1 rendering and names navigation."""
    super_admin = SuperAdminFactory()
    for _ in range(26):
        ModerationCaseFactory(status=CaseStatus.NEW)
    verify_mfa(client, super_admin)

    with CaptureQueriesContext(connection) as queries:
        response = client.get(reverse("moderation:case_queue"))

    content = response.content.decode()
    assert response.status_code == 200
    # SessionSecurityMiddleware adds one constant UserSession lookup per request.
    assert len(queries) <= 6
    assert 'role="status"' in content
    assert 'aria-label="Moderation case pages"' in content
    assert 'aria-current="page"' in content


@pytest.mark.integration
def test_verified_super_admin_can_assign_decide_and_resolve_appeal(client):
    """ADM-002/ADM-004/ADM-007: verified Super Admin workflows use the audited services."""
    super_admin = SuperAdminFactory()
    case = ModerationCaseFactory(status=CaseStatus.NEW)
    verify_mfa(client, super_admin)

    queue = client.get(reverse("moderation:case_queue"))
    assigned = client.post(reverse("moderation:case_assign", kwargs={"pk": case.pk}))
    decision = client.post(
        reverse("moderation:case_decide", kwargs={"pk": case.pk}),
        {
            "action": ModerationAction.WARNING,
            "reason": ReportReason.SPAM,
            "comment": "Repeated abuse",
        },
    )
    case.refresh_from_db()
    appeal(case.report.reporter, case, "This decision is incorrect")
    resolved = client.post(
        reverse("moderation:appeal_resolve", kwargs={"pk": case.pk}),
        {"outcome": AppealStatus.UPHELD, "reason": "Evidence confirms the decision"},
    )

    case.refresh_from_db()
    assert queue.status_code == 200
    assert assigned.status_code == 302
    assert decision.status_code == 302
    assert resolved.status_code == 302
    assert case.assigned_to == super_admin
    assert case.appeal_status == AppealStatus.UPHELD


@pytest.mark.integration
def test_case_queue_order_age_surfaces_oldest_cases_for_sla_triage(client):
    """ADM-002: the allowlisted ?order=age surfaces the oldest cases first for triage."""
    super_admin = SuperAdminFactory()
    now = timezone.now()
    oldest = ModerationCaseFactory()
    middle = ModerationCaseFactory()
    newest = ModerationCaseFactory()
    ModerationCase.objects.filter(pk=oldest.pk).update(created_at=now - timedelta(days=3))
    ModerationCase.objects.filter(pk=middle.pk).update(created_at=now - timedelta(days=2))
    ModerationCase.objects.filter(pk=newest.pk).update(created_at=now - timedelta(days=1))
    verify_mfa(client, super_admin)

    default_page = client.get(reverse("moderation:case_queue"))
    age_page = client.get(reverse("moderation:case_queue"), {"order": "age"})
    forged_page = client.get(
        reverse("moderation:case_queue"), {"order": "report__reporter__username"}
    )

    assert default_page.status_code == 200
    assert [case.pk for case in default_page.context["cases"]] == [newest.pk, middle.pk, oldest.pk]
    assert age_page.status_code == 200
    assert [case.pk for case in age_page.context["cases"]] == [oldest.pk, middle.pk, newest.pk]
    assert age_page.context["filters"]["order"] == "age"
    assert [case.pk for case in forged_page.context["cases"]] == [newest.pk, middle.pk, oldest.pk]
    assert forged_page.context["filters"]["order"] == "newest"


@pytest.mark.integration
def test_report_submission_rejects_requests_without_csrf_token():
    """SEC-008/ADM-003: report submission retains Django CSRF protection."""
    member = UserFactory()
    target = ProjectFactory()
    client = Client(enforce_csrf_checks=True)
    client.force_login(member)

    response = client.post(
        reverse("moderation:report_create"),
        {
            "content_type": ContentType.objects.get_for_model(target).pk,
            "object_id": target.pk,
            "reason": ReportReason.SPAM,
        },
    )

    assert response.status_code == 403
    assert not Report.objects.exists()
