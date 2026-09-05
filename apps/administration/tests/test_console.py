import pytest
from django.urls import reverse

from apps.audit.tests.factories import UserFactory
from apps.ministries.tests.factories import SuperAdminFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _privileged_mfa_bypass(settings):
    settings.PRIVILEGED_MFA_BYPASS = True


@pytest.mark.integration
def test_anonymous_visitor_is_sent_to_sign_in():
    """ADM-002/SEC-005: the administration console is not reachable without authentication."""
    from django.test import Client

    response = Client().get(reverse("administration:console"))

    assert response.status_code == 302
    assert reverse("accounts:login") in response.url


@pytest.mark.integration
def test_member_is_denied_the_console(client):
    """ADM-002/SEC-005: an ordinary member has no administrative access."""
    client.force_login(UserFactory())

    assert client.get(reverse("administration:console")).status_code == 403


@pytest.mark.integration
def test_super_admin_without_verified_mfa_is_sent_to_enrolment(client, settings):
    """ADM-002/AUTH-005: administrative access requires a verified MFA session."""
    settings.PRIVILEGED_MFA_BYPASS = False
    super_admin = SuperAdminFactory()
    super_admin.otp_device = None
    super_admin.is_verified = lambda: False
    client.force_login(super_admin)

    response = client.get(reverse("administration:console"))

    assert response.status_code == 302
    assert response.url == reverse("accounts:mfa_setup")


@pytest.mark.integration
def test_console_lists_every_queue_catalogue_and_oversight_surface(client):
    """ADM-001/ADM-002/ADM-006: the console reaches every privileged surface in one page."""
    client.force_login(SuperAdminFactory())

    response = client.get(reverse("administration:console"))
    content = response.content.decode()

    assert response.status_code == 200
    for destination in (
        reverse("projects:review_queue"),
        reverse("moderation:case_queue"),
        reverse("contributions:verification_queue"),
        reverse("ministries:organization_list"),
        reverse("taxonomy:skill_suggestion_review_list"),
        reverse("recognition:badge_list"),
        reverse("administration:feature_flags"),
        reverse("audit:ops_dashboard"),
        reverse("audit:audit_log"),
        reverse("admin:index"),
    ):
        assert destination in content


@pytest.mark.unit
def test_console_covers_every_administrative_queue():
    """ADM-002: the console enumerates each queue a Super Admin is accountable for."""
    from apps.administration.console import build_work_queues

    assert {queue["id"] for queue in build_work_queues()} == {
        "project_reviews",
        "moderation_cases",
        "appeals",
        "contribution_verifications",
        "skill_suggestions",
        "ministry_provisioning",
    }


@pytest.mark.integration
def test_review_queue_count_tracks_submissions_awaiting_a_decision():
    """ADM-002/GOV-005: only submissions still needing a ruling are counted as outstanding."""
    from apps.administration.console import build_work_queues
    from apps.projects.enums import ProjectStatus
    from apps.projects.tests.factories import ProjectFactory

    def review_count():
        return next(queue for queue in build_work_queues() if queue["id"] == "project_reviews")[
            "count"
        ]

    assert review_count() == 0

    ProjectFactory(status=ProjectStatus.IN_REVIEW)
    ProjectFactory(status=ProjectStatus.CHANGES_REQUESTED)
    ProjectFactory(status=ProjectStatus.OPEN_FOR_CONTRIBUTION)

    assert review_count() == 2


@pytest.mark.integration
def test_console_reports_the_total_outstanding_workload(client):
    """ADM-006: the console states how much administrative work is waiting overall."""
    from apps.projects.enums import ProjectStatus
    from apps.projects.tests.factories import ProjectFactory

    ProjectFactory(status=ProjectStatus.IN_REVIEW)
    client.force_login(SuperAdminFactory())

    response = client.get(reverse("administration:console"))

    assert response.status_code == 200
    assert response.context["outstanding"] >= 1
