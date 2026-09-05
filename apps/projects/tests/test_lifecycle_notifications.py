import logging

import pytest

from apps.ministries.tests.factories import MinistryPublisherFactory
from apps.notifications.enums import Channel, NotificationType
from apps.notifications.models import Notification
from apps.projects.enums import ApplicationStatus, ProjectStatus
from apps.projects.models import ProjectBookmark
from apps.projects.services import (
    apply_to_project,
    approve,
    decide_application,
    publish,
    publish_due_scheduled,
    request_changes,
    submit_for_review,
)
from apps.projects.tests.factories import SuperAdminFactory, UserFactory, make_publishable

pytestmark = pytest.mark.django_db


@pytest.mark.integration
def test_review_approval_and_publication_notify_only_relevant_recipients(
    django_capture_on_commit_callbacks,
):
    """GOV-004/GOV-005/DSC-004/NTF-001: lifecycle decisions notify owners and opted-in followers."""
    project = make_publishable()
    publisher = project.owner
    reviewer = SuperAdminFactory()
    follower = UserFactory()
    quiet_follower = UserFactory()
    ProjectBookmark.objects.create(user=follower, project=project, notify_on_change=True)
    ProjectBookmark.objects.create(user=quiet_follower, project=project, notify_on_change=False)

    with django_capture_on_commit_callbacks(execute=True):
        submit_for_review(publisher, project)
    with django_capture_on_commit_callbacks(execute=True):
        request_changes(reviewer, project, reason="Clarify the scope")
    with django_capture_on_commit_callbacks(execute=True):
        submit_for_review(publisher, project)
    with django_capture_on_commit_callbacks(execute=True):
        approve(reviewer, project)
    with django_capture_on_commit_callbacks(execute=True):
        publish(reviewer, project)

    assert (
        Notification.objects.filter(
            recipient=publisher,
            channel=Channel.IN_APP,
            type=NotificationType.REVIEW_COMMENT,
        ).count()
        == 1
    )
    assert (
        Notification.objects.filter(
            recipient=publisher,
            channel=Channel.IN_APP,
            type=NotificationType.REVIEW_DECISION,
        ).count()
        == 1
    )
    assert (
        Notification.objects.filter(
            recipient=follower,
            channel=Channel.IN_APP,
            type=NotificationType.PROJECT_STATUS,
        ).count()
        == 1
    )
    assert not Notification.objects.filter(recipient=quiet_follower).exists()


@pytest.mark.integration
def test_application_submission_and_decision_notify_authorized_recipients(
    django_capture_on_commit_callbacks,
):
    """DSC-007/DSC-008/NTF-001/NTF-003: application events stay private to authorized users."""
    project = make_publishable(status=ProjectStatus.OPEN_FOR_CONTRIBUTION)
    additional_publisher = UserFactory()
    MinistryPublisherFactory(user=additional_publisher, ministry=project.ministry)
    applicant = UserFactory()

    with django_capture_on_commit_callbacks(execute=True):
        application = apply_to_project(applicant, project, motivation="Private application detail")

    assert Notification.objects.filter(
        recipient=project.owner,
        channel=Channel.IN_APP,
        type=NotificationType.APPLICATION_STATUS,
        context_url=f"/applications/{application.pk}/",
    ).exists()
    assert Notification.objects.filter(
        recipient=additional_publisher,
        channel=Channel.IN_APP,
        type=NotificationType.APPLICATION_STATUS,
    ).exists()
    assert not Notification.objects.filter(recipient=applicant).exists()

    with django_capture_on_commit_callbacks(execute=True):
        decide_application(
            project.owner,
            application,
            ApplicationStatus.INFO_REQUESTED,
            note="Private request detail",
        )

    notification = Notification.objects.get(
        recipient=applicant,
        channel=Channel.IN_APP,
        type=NotificationType.APPLICATION_STATUS,
    )
    assert notification.context_url == f"/applications/{application.pk}/"
    assert "Private request detail" not in notification.title
    assert "Private request detail" not in notification.body


@pytest.mark.integration
def test_scheduled_publication_notification_is_idempotent(django_capture_on_commit_callbacks):
    """GOV-004/DSC-004/NTF-004: repeated scheduled publication processing creates one event."""
    project = make_publishable()
    follower = UserFactory()
    ProjectBookmark.objects.create(user=follower, project=project, notify_on_change=True)
    reviewer = SuperAdminFactory()

    with django_capture_on_commit_callbacks(execute=True):
        submit_for_review(project.owner, project)
        approve(reviewer, project)
        project.scheduled_publication_at = project.status_changed_at
        project.save(update_fields=["scheduled_publication_at"])
        publish_due_scheduled(now=project.scheduled_publication_at)
        publish_due_scheduled(now=project.scheduled_publication_at)

    assert (
        Notification.objects.filter(
            recipient=follower,
            channel=Channel.IN_APP,
            type=NotificationType.PROJECT_STATUS,
        ).count()
        == 1
    )


@pytest.mark.integration
def test_notification_failure_does_not_rollback_lifecycle_transition(
    django_capture_on_commit_callbacks, monkeypatch, caplog
):
    """GOV-004/NTF-004: a notification failure leaves the review transition committed."""
    project = make_publishable()
    reviewer = SuperAdminFactory()

    with django_capture_on_commit_callbacks(execute=True):
        submit_for_review(project.owner, project)

    def fail_notify(*args, **kwargs):
        raise RuntimeError("notification storage unavailable")

    monkeypatch.setattr("apps.projects.services.notify", fail_notify)
    with caplog.at_level(logging.ERROR):
        with django_capture_on_commit_callbacks(execute=True):
            request_changes(reviewer, project, reason="Clarify the scope")

    project.refresh_from_db()
    assert project.status == ProjectStatus.CHANGES_REQUESTED
    assert "notification delivery setup failed" in caplog.text
