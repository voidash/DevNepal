import datetime
from unittest import mock

import pytest
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.audit.tests.factories import AuditEventFactory, UserFactory
from apps.audit.tests.test_views import verify_mfa
from apps.github_sync.enums import ProcessingState, SyncState
from apps.github_sync.tests.factories import ProviderEventFactory, RepositoryConnectionFactory
from apps.ministries.tests.factories import SuperAdminFactory
from apps.moderation.enums import CaseStatus
from apps.moderation.tests.factories import ModerationCaseFactory
from apps.notifications.enums import DeliveryStatus
from apps.notifications.tests.factories import NotificationFactory
from apps.projects.enums import ProjectStatus
from apps.projects.models import Project
from apps.projects.tests.factories import ProjectFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def ops_urlconf():
    with override_settings(ROOT_URLCONF="apps.audit.tests.urls"):
        yield


def panel_by_id(response, panel_id):
    return next(panel for panel in response.context["panels"] if panel["id"] == panel_id)


def moment_from_now(**offset):
    return timezone.now() + datetime.timedelta(**offset)


def date_from_today(**offset):
    return timezone.localdate() + datetime.timedelta(**offset)


def stale_project(**kwargs):
    kwargs.setdefault("status", ProjectStatus.PAUSED)
    kwargs.setdefault("deadline", date_from_today(days=-2))
    return ProjectFactory(**kwargs)


def aging_case(**kwargs):
    kwargs.setdefault("created_at", moment_from_now(days=-6))
    created_at = kwargs.pop("created_at")
    with mock.patch("django.utils.timezone.now", return_value=created_at):
        return ModerationCaseFactory(**kwargs)


def audit_event_at(moment, **kwargs):
    with mock.patch("django.utils.timezone.now", return_value=moment):
        return AuditEventFactory(**kwargs)


def test_anonymous_user_is_redirected_to_login(client):
    """ADM-006: the operations dashboard is not reachable without authentication."""
    response = client.get(reverse("audit:ops_dashboard"))

    assert response.status_code == 302
    assert reverse("accounts:login") in response.url


def test_non_superadmin_receives_403(client):
    """ADM-006: authenticated non-superadmins are denied the operations dashboard."""
    member = UserFactory()
    client.force_login(member)

    response = client.get(reverse("audit:ops_dashboard"))

    assert response.status_code == 403


def test_unverified_super_admin_is_redirected_to_mfa(client):
    """ADM-006/AUTH-005: dashboard access requires a verified MFA session."""
    super_admin = SuperAdminFactory()
    super_admin.otp_device = None
    super_admin.is_verified = lambda: False
    client.force_login(super_admin)

    response = client.get(reverse("audit:ops_dashboard"))

    assert response.status_code == 302
    assert response.url == reverse("accounts:mfa_setup")


def test_verified_super_admin_sees_five_panels_with_source_links(client):
    """ADM-006/NFR-OBS-01: five panels render with counts and links to their source pages."""
    super_admin = SuperAdminFactory()
    stale_project(title_en="Stale Paused Service")
    aging_case(status=CaseStatus.NEW)
    RepositoryConnectionFactory(sync_state=SyncState.DEGRADED)
    NotificationFactory(recipient=UserFactory(), delivery_status=DeliveryStatus.FAILED)
    AuditEventFactory(action="project.publish", result="failure")
    verify_mfa(client, super_admin)

    response = client.get(reverse("audit:ops_dashboard"))
    content = response.content.decode()

    assert response.status_code == 200
    assert reverse("projects:list") in content
    assert reverse("moderation:case_queue") in content
    assert reverse("github_sync:connection") in content
    assert reverse("notifications:list") in content
    assert reverse("audit:audit_log") in content
    assert "Stale or expired projects" in content
    assert "Aging moderation cases" in content
    assert "Repository sync health" in content
    assert "Notification delivery backlog" in content
    assert "Recent audit failures and denials" in content
    assert "Stale Paused Service" in content


def test_stale_project_panel_filters_by_live_status_and_past_deadline(client):
    """ADM-006: only live projects (paused or open) past their deadline are flagged."""
    super_admin = SuperAdminFactory()
    paused = stale_project(title_en="Paused Past Deadline")
    expired_open = stale_project(
        title_en="Open Past Deadline",
        status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
        deadline=date_from_today(days=-1),
    )
    stale_project(title_en="Future Deadline", deadline=date_from_today(days=7))
    stale_project(title_en="Completed Not Stale", status=ProjectStatus.COMPLETED)
    stale_project(title_en="No Deadline", deadline=None)
    verify_mfa(client, super_admin)

    response = client.get(reverse("audit:ops_dashboard"))
    panel = panel_by_id(response, "stale_projects")
    content = response.content.decode()

    assert {row.pk for row in panel["rows"]} == {paused.pk, expired_open.pk}
    assert "Paused Past Deadline" in content
    assert "Open Past Deadline" in content
    assert "Future Deadline" not in content
    assert "Completed Not Stale" not in content
    assert "No Deadline" not in content
    assert "is-attention" in content


def test_aging_moderation_panel_uses_five_day_threshold(client):
    """ADM-006/ADM-002: only NEW and UNDER_REVIEW cases older than five days are flagged."""
    super_admin = SuperAdminFactory()
    old_new = aging_case(status=CaseStatus.NEW, created_at=moment_from_now(days=-6))
    old_review = aging_case(status=CaseStatus.UNDER_REVIEW, created_at=moment_from_now(days=-7))
    aging_case(status=CaseStatus.NEW, created_at=moment_from_now(days=-1))
    aging_case(status=CaseStatus.ACTION_TAKEN, created_at=moment_from_now(days=-30))
    verify_mfa(client, super_admin)

    response = client.get(reverse("audit:ops_dashboard"))
    panel = panel_by_id(response, "aging_cases")

    assert {row.pk for row in panel["rows"]} == {old_new.pk, old_review.pk}
    assert "is-attention" in response.content.decode()


def test_repository_health_panel_lists_unhealthy_connections_and_pending_backlog(client):
    """ADM-006/GIT-011: degraded and error connections are listed with the pending backlog."""
    super_admin = SuperAdminFactory()
    degraded = RepositoryConnectionFactory(sync_state=SyncState.DEGRADED)
    errored = RepositoryConnectionFactory(sync_state=SyncState.ERROR)
    RepositoryConnectionFactory(sync_state=SyncState.IDLE)
    ProviderEventFactory(processing_state=ProcessingState.PENDING)
    ProviderEventFactory(processing_state=ProcessingState.PENDING)
    ProviderEventFactory(processing_state=ProcessingState.PROCESSED)
    verify_mfa(client, super_admin)

    response = client.get(reverse("audit:ops_dashboard"))
    panel = panel_by_id(response, "repo_health")
    content = response.content.decode()

    assert {row.pk for row in panel["rows"]} == {degraded.pk, errored.pk}
    assert panel["pending_events"] == 2
    assert degraded.full_name in content
    assert errored.full_name in content
    assert "is-danger" in content


def test_notification_delivery_panel_counts_pending_and_failed(client):
    """ADM-006/NTF-004: pending and failed delivery rows are counted per status."""
    super_admin = SuperAdminFactory()
    NotificationFactory(recipient=UserFactory(), delivery_status=DeliveryStatus.PENDING)
    NotificationFactory(recipient=UserFactory(), delivery_status=DeliveryStatus.PENDING)
    NotificationFactory(recipient=UserFactory(), delivery_status=DeliveryStatus.FAILED)
    NotificationFactory(recipient=UserFactory(), delivery_status=DeliveryStatus.SENT)
    verify_mfa(client, super_admin)

    response = client.get(reverse("audit:ops_dashboard"))
    panel = panel_by_id(response, "notification_delivery")

    assert panel["count"] == 3
    assert {(row["status"], row["total"]) for row in panel["rows"]} == {
        (DeliveryStatus.PENDING, 2),
        (DeliveryStatus.FAILED, 1),
    }
    assert "is-attention" in response.content.decode()


def test_audit_failure_panel_covers_24h_and_links_to_filtered_log(client):
    """NFR-OBS-01/ADM-006: 24h failed/denied events link to the filtered audit log."""
    super_admin = SuperAdminFactory()
    fresh_failure = audit_event_at(
        moment_from_now(hours=-1), action="project.publish", result="failure"
    )
    fresh_denial = audit_event_at(
        moment_from_now(hours=-2), action="role.grant.super_admin", result="denied"
    )
    audit_event_at(moment_from_now(hours=-25), action="project.publish", result="failure")
    audit_event_at(moment_from_now(hours=-1), action="project.review", result="success")
    verify_mfa(client, super_admin)

    response = client.get(reverse("audit:ops_dashboard"))
    panel = panel_by_id(response, "recent_audit_failures")
    content = response.content.decode()

    assert [row.pk for row in panel["rows"]] == [fresh_denial.pk, fresh_failure.pk]
    assert f"{reverse('audit:audit_log')}?result=failure" in content
    assert f"{reverse('audit:audit_log')}?result=denied" in content
    assert "project.publish" in content
    assert "role.grant.super_admin" in content
    assert "is-danger" in content


def test_panels_cap_rows_at_five_and_signal_overflow(client):
    """ADM-006: panels render at most five rows and signal when more entries exist."""
    super_admin = SuperAdminFactory()
    for offset in range(6):
        stale_project(
            title_en=f"Stale Project {offset}",
            deadline=date_from_today(days=-(offset + 1)),
        )
    verify_mfa(client, super_admin)

    response = client.get(reverse("audit:ops_dashboard"))
    panel = panel_by_id(response, "stale_projects")
    content = response.content.decode()

    assert len(panel["rows"]) == 5
    assert panel["overflow"] is True
    assert "Stale Project 0" not in content
    assert "Stale Project 5" in content
    assert "More entries exist" in content


def test_dashboard_is_get_only_and_records_no_mutation(client):
    """ADM-008/ADM-005: the dashboard is read-only GET with no export surface."""
    super_admin = SuperAdminFactory()
    stale_project()
    verify_mfa(client, super_admin)

    post = client.post(reverse("audit:ops_dashboard"), {"action": "refresh"})
    delete_attempt = client.delete(reverse("audit:ops_dashboard"))

    assert post.status_code == 405
    assert delete_attempt.status_code == 405
    assert Project.objects.count() == 1


def test_page_query_count_is_bounded(client):
    """NFR-OBS-01: the whole dashboard render stays within a fixed query budget."""
    super_admin = SuperAdminFactory()
    for offset in range(6):
        stale_project(title_en=f"Stale {offset}", deadline=date_from_today(days=-(offset + 1)))
        aging_case(status=CaseStatus.NEW, created_at=moment_from_now(days=-(offset + 6)))
    RepositoryConnectionFactory(sync_state=SyncState.DEGRADED)
    RepositoryConnectionFactory(sync_state=SyncState.ERROR)
    ProviderEventFactory(processing_state=ProcessingState.PENDING)
    NotificationFactory(recipient=UserFactory(), delivery_status=DeliveryStatus.PENDING)
    NotificationFactory(recipient=UserFactory(), delivery_status=DeliveryStatus.FAILED)
    audit_event_at(moment_from_now(hours=-1), action="project.publish", result="failure")
    verify_mfa(client, super_admin)

    with CaptureQueriesContext(connection) as queries:
        response = client.get(reverse("audit:ops_dashboard"))

    assert response.status_code == 200
    assert len(queries) <= 12
