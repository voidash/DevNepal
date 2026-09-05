import pytest
from django.core import mail
from django.core.management import CommandError, call_command

from apps.accounts.tests.factories import UserFactory
from apps.notifications.enums import Channel, DeliveryStatus, DigestFrequency, NotificationType
from apps.notifications.models import Notification
from apps.notifications.services import MAX_DELIVERY_ATTEMPTS, notify, safe_subject
from apps.notifications.tests.factories import (
    NotificationFactory,
    NotificationPreferenceFactory,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

COMMAND = "send_pending_notifications"


def pending_email_row(user, type_, context_url, **kwargs):
    return NotificationFactory(
        recipient=user,
        channel=Channel.EMAIL,
        type=type_,
        delivery_status=DeliveryStatus.PENDING,
        title=safe_subject(type_),
        body="Sign in to DevNepal to view the details.",
        context_url=context_url,
        **kwargs,
    )


def test_ntf004_command_sends_pending_email_rows_and_marks_them_sent(mailoutbox):
    """NTF-004: queued email rows are delivered through the mail backend and marked sent."""
    member = UserFactory()
    row = pending_email_row(member, NotificationType.REVIEW_COMMENT, "/contributions/9/")

    call_command(COMMAND, stdout=__import__("io").StringIO())

    row.refresh_from_db()
    assert row.delivery_status == DeliveryStatus.SENT
    assert row.last_attempt_at is not None
    assert len(mailoutbox) == 1
    assert mailoutbox[0].to == [member.email]


def test_ntf003_email_content_stays_generic_with_internal_link_only(mailoutbox):
    """NTF-003: the sent email subject is generic and the body carries no context PII."""
    member = UserFactory()
    notify(
        member,
        NotificationType.APPLICATION_STATUS,
        {
            "context_url": "/applications/7/",
            "applicant_name": "Sita Karki",
            "project_title": "National ID Rewrite",
        },
    )

    call_command(COMMAND, stdout=__import__("io").StringIO())

    message = mail.outbox[0]
    assert message.subject == safe_subject(NotificationType.APPLICATION_STATUS)
    assert "Sita Karki" not in message.subject
    assert "National ID Rewrite" not in message.subject
    assert "Sita Karki" not in message.body
    assert "National ID Rewrite" not in message.body
    assert "/applications/7/" in message.body


def test_ntf002_opted_out_member_email_is_skipped(mailoutbox):
    """NTF-002: the worker never sends email for a category the member opted out of."""
    member = UserFactory()
    NotificationPreferenceFactory(user=member, email_community=False)
    row = pending_email_row(member, NotificationType.PROJECT_UPDATE, "/projects/1/")

    call_command(COMMAND, stdout=__import__("io").StringIO())

    row.refresh_from_db()
    assert row.delivery_status == DeliveryStatus.SUPPRESSED
    assert mailoutbox == []


def test_ntf002_mandatory_notices_are_sent_despite_opt_out(mailoutbox):
    """NTF-002: security notices bypass every opt-out and still reach the member."""
    member = UserFactory()
    NotificationPreferenceFactory(
        user=member,
        email_applications=False,
        email_reviews=False,
        email_contributions=False,
        email_community=False,
    )
    row = pending_email_row(member, NotificationType.SECURITY, "/account/security/")

    call_command(COMMAND, stdout=__import__("io").StringIO())

    row.refresh_from_db()
    assert row.delivery_status == DeliveryStatus.SENT
    assert len(mailoutbox) == 1
    assert mailoutbox[0].subject == safe_subject(NotificationType.SECURITY)


def test_ntf004_send_failure_keeps_row_retryable_and_next_run_succeeds(
    mailoutbox, monkeypatch, caplog
):
    """NTF-004: a failed send is logged, keeps the row in the retry queue, and is retried."""
    member = UserFactory()
    row = pending_email_row(member, NotificationType.REVIEW_COMMENT, "/contributions/3/")

    def boom(*args, **kwargs):
        raise ConnectionRefusedError("smtp refused")

    monkeypatch.setattr("apps.notifications.services.send_mail", boom)
    with pytest.raises(CommandError):
        call_command(COMMAND, stdout=__import__("io").StringIO())

    row.refresh_from_db()
    assert row.delivery_status == DeliveryStatus.FAILED
    assert row.delivery_attempts == 1
    assert row.last_error_class == "ConnectionRefusedError"
    assert "send_pending_notifications" in caplog.text
    assert mailoutbox == []

    monkeypatch.undo()
    call_command(COMMAND, stdout=__import__("io").StringIO())

    row.refresh_from_db()
    assert row.delivery_status == DeliveryStatus.SENT
    assert len(mailoutbox) == 1


def test_ntf004_exhausted_rows_are_not_retried_again(mailoutbox, monkeypatch):
    """NTF-004: rows past the retry budget never send again (no retry storm)."""
    member = UserFactory()
    row = pending_email_row(member, NotificationType.REVIEW_COMMENT, "/contributions/4/")
    row.delivery_status = DeliveryStatus.FAILED
    row.delivery_attempts = MAX_DELIVERY_ATTEMPTS
    row.save(update_fields=["delivery_status", "delivery_attempts"])

    call_command(COMMAND, stdout=__import__("io").StringIO())

    assert mailoutbox == []
    row.refresh_from_db()
    assert row.delivery_status == DeliveryStatus.FAILED


def test_ntf004_second_run_never_duplicates_sends(mailoutbox):
    """NTF-004: rerunning the worker sends each queued email exactly once."""
    member = UserFactory()
    notify(member, NotificationType.REVIEW_COMMENT, {"context_url": "/contributions/1/"})
    notify(member, NotificationType.APPLICATION_STATUS, {"context_url": "/applications/2/"})

    call_command(COMMAND, stdout=__import__("io").StringIO())
    call_command(COMMAND, stdout=__import__("io").StringIO())

    assert len(mailoutbox) == 2
    assert (
        Notification.objects.filter(
            recipient=member,
            channel=Channel.EMAIL,
            delivery_status=DeliveryStatus.SENT,
        ).count()
        == 2
    )


def test_ntf002_digest_member_receives_one_aggregated_email(mailoutbox):
    """NTF-002: digest users' pending rows group into a single generic email."""
    member = UserFactory()
    NotificationPreferenceFactory(user=member, digest_frequency=DigestFrequency.DAILY)
    notify(member, NotificationType.REVIEW_COMMENT, {"context_url": "/contributions/11/"})
    notify(member, NotificationType.APPLICATION_STATUS, {"context_url": "/applications/12/"})
    stranger = UserFactory()
    notify(stranger, NotificationType.REVIEW_COMMENT, {"context_url": "/contributions/13/"})

    call_command(COMMAND, stdout=__import__("io").StringIO())

    member_messages = [message for message in mail.outbox if message.to == [member.email]]
    assert len(member_messages) == 1
    digest = member_messages[0]
    assert digest.subject == safe_subject(NotificationType.REVIEW_COMMENT)
    assert "/contributions/11/" in digest.body
    assert "/applications/12/" in digest.body
    assert (
        Notification.objects.filter(
            recipient=member, channel=Channel.EMAIL, delivery_status=DeliveryStatus.SENT
        ).count()
        == 2
    )


def test_ntf004_in_app_rows_are_never_emailed(mailoutbox):
    """NTF-004: the worker drains the email channel only; in-app rows stay delivered."""
    member = UserFactory()
    notify(member, NotificationType.REVIEW_COMMENT, {"context_url": "/contributions/1/"})

    call_command(COMMAND, stdout=__import__("io").StringIO())

    in_app = Notification.objects.get(recipient=member, channel=Channel.IN_APP)
    assert in_app.delivery_status == DeliveryStatus.DELIVERED
    assert len(mailoutbox) == 1


def test_ntf004_command_help_documents_worker_usage():
    """NTF-004: the command help tells operators how to schedule the worker."""

    from apps.notifications.management.commands.send_pending_notifications import Command

    help_text = Command.help.lower()
    assert "worker" in help_text
    assert "cron" in help_text or "schedule" in help_text
    assert "re-run" in help_text or "rerun" in help_text or "idempotent" in help_text
