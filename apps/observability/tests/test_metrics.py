import datetime
from unittest import mock

import pytest
from django.utils import timezone

from apps.audit.tests.factories import AuditEventFactory
from apps.github_sync.enums import ProcessingState
from apps.github_sync.tests.factories import ProviderEventFactory
from apps.moderation.enums import CaseStatus
from apps.moderation.tests.factories import ModerationCaseFactory
from apps.notifications.enums import DeliveryStatus
from apps.notifications.tests.factories import NotificationFactory
from apps.observability.metrics import (
    _audit_failures_24h,
    _github_sync_pending_events,
    _moderation_aging_cases,
    _notifications_pending,
    _seconds_since_last_success,
    _stale_projects,
)
from apps.projects.enums import ProjectStatus
from apps.projects.tests.factories import ProjectFactory

pytestmark = [pytest.mark.django_db, pytest.mark.unit]


def test_github_sync_pending_events_counts_only_pending_rows():
    """NFR-OBS-01: the pending-events gauge feeds the repository-sync-health dashboard panel."""
    ProviderEventFactory(processing_state=ProcessingState.PENDING)
    ProviderEventFactory(processing_state=ProcessingState.PROCESSED)
    assert _github_sync_pending_events() == 1


def test_notifications_pending_counts_pending_and_failed_deliveries():
    """NFR-OBS-01: the notification-backlog gauge mirrors the existing ops-panel definition."""
    NotificationFactory(delivery_status=DeliveryStatus.PENDING)
    NotificationFactory(delivery_status=DeliveryStatus.FAILED)
    NotificationFactory(delivery_status=DeliveryStatus.SENT)
    assert _notifications_pending() == 2


def test_moderation_aging_cases_excludes_recent_cases():
    """NFR-OBS-01: only moderation cases open for more than five days count as aging."""
    old_case = ModerationCaseFactory(status=CaseStatus.NEW)
    old_case.created_at = timezone.now() - datetime.timedelta(days=6)
    old_case.save(update_fields=["created_at"])
    ModerationCaseFactory(status=CaseStatus.NEW)
    assert _moderation_aging_cases() == 1


def test_stale_projects_counts_only_open_projects_past_their_deadline():
    """NFR-OBS-01: the stale-projects gauge mirrors the existing ops-panel definition."""
    ProjectFactory(
        status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
        deadline=timezone.localdate() - datetime.timedelta(days=1),
    )
    ProjectFactory(
        status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
        deadline=timezone.localdate() + datetime.timedelta(days=1),
    )
    assert _stale_projects() == 1


def test_seconds_since_last_success_is_infinite_when_the_job_has_never_succeeded():
    """NFR-OBS-01/NFR-AVL-02: a never-run job must trip the staleness alert, not stay silent."""
    assert _seconds_since_last_success("a_command_with_no_job_runs_at_all") == float("inf")


def test_audit_failures_24h_excludes_older_events():
    """NFR-OBS-01: the audit-failure gauge only looks back 24 hours."""
    AuditEventFactory(result="failure")
    stale_moment = timezone.now() - datetime.timedelta(hours=25)
    with mock.patch("django.utils.timezone.now", return_value=stale_moment):
        AuditEventFactory(result="denied")
    assert _audit_failures_24h() == 1
