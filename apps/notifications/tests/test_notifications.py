import datetime

import pytest
from django.test import override_settings
from django.urls import reverse

from apps.accounts.tests.factories import UserFactory
from apps.audit.models import AuditEvent
from apps.notifications.enums import (
    Channel,
    DeliveryStatus,
    DigestFrequency,
    NotificationType,
)
from apps.notifications.models import Notification
from apps.notifications.services import (
    collect_digest,
    digest_cutoff,
    mark_read,
    notifications_for,
    notify,
    record_delivery_failure,
    retry_candidates,
    safe_subject,
    unread_count,
)
from apps.notifications.tests.factories import NotificationFactory

pytestmark = pytest.mark.django_db


NOTIFICATION_URLCONF = override_settings(ROOT_URLCONF="apps.notifications.tests.urls")


ALL_TYPES = [value for value, _label in NotificationType.choices]

EVENT_CONTEXTS = {
    NotificationType.APPLICATION_STATUS: {
        "context_url": "/applications/123/",
        "status": "approved",
        "applicant_name": "Sita Karki",
    },
    NotificationType.REVIEW_DECISION: {"context_url": "/projects/1/review/"},
    NotificationType.REVIEW_COMMENT: {"context_url": "/contributions/9/"},
    NotificationType.ASSIGNMENT: {"context_url": "/projects/1/assignments/"},
    NotificationType.CONTRIBUTION_VERIFIED: {"context_url": "/contributions/9/"},
    NotificationType.CONTRIBUTION_REVOKED: {"context_url": "/contributions/9/"},
    NotificationType.BADGE_AWARDED: {"context_url": "/badges/"},
    NotificationType.PROJECT_UPDATE: {"context_url": "/projects/1/"},
    NotificationType.PROJECT_STATUS: {"context_url": "/projects/1/"},
    NotificationType.BOOKMARK_CHANGE: {"context_url": "/projects/1/"},
    NotificationType.MODERATION: {"context_url": "/moderation/cases/5/"},
    NotificationType.SECURITY: {"context_url": "/account/security/"},
    NotificationType.ACCOUNT: {"context_url": "/account/"},
}


@pytest.mark.integration
@pytest.mark.parametrize("notification_type", ALL_TYPES)
def test_ntf001_u1_every_workflow_event_creates_in_app_notification(notification_type):
    """NTF-001-U1: each workflow event type produces an in-app notification for the user."""
    user = UserFactory()

    created = notify(user, notification_type, EVENT_CONTEXTS[notification_type])

    assert created.recipient == user
    assert created.type == notification_type
    assert created.channel == Channel.IN_APP
    assert created.title
    assert created.delivery_status == DeliveryStatus.DELIVERED


@pytest.mark.integration
def test_ntf001_i1_user_sees_only_own_notifications():
    """NTF-001-I1: notification listings and unread counts are scoped to the recipient."""
    mine, other = UserFactory(), UserFactory()
    notify(mine, NotificationType.REVIEW_COMMENT, {"context_url": "/contributions/1/"})
    notify(other, NotificationType.REVIEW_COMMENT, {"context_url": "/contributions/2/"})

    listed = list(notifications_for(mine))

    assert [n.recipient for n in listed] == [mine]
    assert unread_count(mine) == 1
    assert unread_count(other) == 1


@pytest.mark.integration
def test_ntf001_both_channels_cover_material_events():
    """NTF-001: material workflow events are covered by both in-app and email channels."""
    user = UserFactory()

    created = notify(user, NotificationType.APPLICATION_STATUS, {"context_url": "/applications/1/"})

    email_rows = Notification.objects.filter(recipient=user, channel=Channel.EMAIL)
    assert created.channel == Channel.IN_APP
    assert email_rows.count() == 1
    assert email_rows.first().type == NotificationType.APPLICATION_STATUS


@pytest.mark.integration
def test_ntf002_u1_preference_toggle_suppresses_nonessential_email():
    """NTF-002-U1: a disabled non-essential email category suppresses the email copy."""
    from apps.notifications.tests.factories import NotificationPreferenceFactory

    user = UserFactory()
    NotificationPreferenceFactory(user=user, email_applications=False)

    notify(user, NotificationType.APPLICATION_STATUS, {"context_url": "/applications/1/"})

    email_row = Notification.objects.get(recipient=user, channel=Channel.EMAIL)
    in_app_row = Notification.objects.get(recipient=user, channel=Channel.IN_APP)
    assert email_row.delivery_status == DeliveryStatus.SUPPRESSED
    assert in_app_row.delivery_status == DeliveryStatus.DELIVERED


@pytest.mark.integration
@pytest.mark.parametrize(
    "mandatory_type",
    [NotificationType.SECURITY, NotificationType.ACCOUNT, NotificationType.MODERATION],
)
def test_ntf002_u1_mandatory_notices_cannot_be_disabled(mandatory_type):
    """NTF-002: mandatory security/administrative notices bypass every email opt-out."""
    from apps.notifications.tests.factories import NotificationPreferenceFactory

    user = UserFactory()
    NotificationPreferenceFactory(
        user=user,
        email_applications=False,
        email_reviews=False,
        email_contributions=False,
        email_community=False,
    )

    notify(user, mandatory_type, {"context_url": "/account/security/"})

    email_row = Notification.objects.get(recipient=user, channel=Channel.EMAIL)
    assert email_row.delivery_status == DeliveryStatus.PENDING


@pytest.mark.integration
def test_ntf002_mandatory_flag_overrides_preferences():
    """NTF-002: an explicit mandatory flag delivers email even for a non-essential type."""
    from apps.notifications.tests.factories import NotificationPreferenceFactory

    user = UserFactory()
    NotificationPreferenceFactory(user=user, email_contributions=False)

    notify(
        user,
        NotificationType.CONTRIBUTION_VERIFIED,
        {"context_url": "/contributions/1/"},
        mandatory=True,
    )

    email_row = Notification.objects.get(recipient=user, channel=Channel.EMAIL)
    assert email_row.delivery_status == DeliveryStatus.PENDING


@pytest.mark.integration
def test_ntf002_u2_digest_frequency_groups_pending_email():
    """NTF-002-U2: digest users' email copies stay pending and group into one digest."""
    from apps.notifications.tests.factories import NotificationPreferenceFactory

    user, stranger = UserFactory(), UserFactory()
    NotificationPreferenceFactory(user=user, digest_frequency=DigestFrequency.DAILY)

    notify(user, NotificationType.REVIEW_COMMENT, {"context_url": "/contributions/1/"})
    notify(user, NotificationType.APPLICATION_STATUS, {"context_url": "/applications/1/"})
    notify(stranger, NotificationType.REVIEW_COMMENT, {"context_url": "/contributions/2/"})

    digest = list(collect_digest(user))

    assert {n.type for n in digest} == {
        NotificationType.REVIEW_COMMENT,
        NotificationType.APPLICATION_STATUS,
    }
    assert all(n.recipient == user for n in digest)
    assert all(n.delivery_status == DeliveryStatus.PENDING for n in digest)


@pytest.mark.integration
def test_ntf002_u2_digest_disabled_users_are_not_grouped():
    """NTF-002-U2: users without a digest frequency never enter the digest queue."""
    user = UserFactory()

    notify(user, NotificationType.REVIEW_COMMENT, {"context_url": "/contributions/1/"})

    assert list(collect_digest(user)) == []


@pytest.mark.unit
def test_ntf002_u2_digest_cutoff_windows_use_frozen_clock():
    """NTF-002-U2: digest cutoffs are exact per frequency (no wall-clock dependency)."""
    frozen = datetime.datetime(2026, 1, 2, 12, 0, tzinfo=datetime.UTC)

    assert digest_cutoff(DigestFrequency.DAILY, frozen) == datetime.datetime(
        2026, 1, 1, 12, 0, tzinfo=datetime.UTC
    )
    assert digest_cutoff(DigestFrequency.WEEKLY, frozen) == datetime.datetime(
        2025, 12, 26, 12, 0, tzinfo=datetime.UTC
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    ("leaky_subject", "pii"),
    [
        ("Your application from Sita Karki was approved", "Sita Karki"),
        ("Review decision for project 'National ID Rewrite'", "National ID Rewrite"),
        ("Contribution verified — contact sita.karki@example.com", "sita.karki@example.com"),
    ],
)
def test_ntf003_u1_subject_lines_never_carry_sensitive_content(leaky_subject, pii):
    """NTF-003-U1: caller-supplied subjects with PII are replaced by generic ones."""
    user = UserFactory()

    notify(
        user,
        NotificationType.APPLICATION_STATUS,
        {"context_url": "/applications/1/", "applicant_name": "Sita Karki"},
        email_subject=leaky_subject,
    )

    email_row = Notification.objects.get(recipient=user, channel=Channel.EMAIL)
    assert email_row.title == safe_subject(NotificationType.APPLICATION_STATUS)
    assert pii not in email_row.title


@pytest.mark.integration
def test_ntf003_u1_allowlisted_generic_subject_passes_through():
    """NTF-003-U1: only allowlisted generic subjects may appear in the email row."""
    user = UserFactory()
    generic = safe_subject(NotificationType.SECURITY)

    notify(user, NotificationType.SECURITY, {}, email_subject=generic)

    email_row = Notification.objects.get(recipient=user, channel=Channel.EMAIL)
    assert email_row.title == generic


@pytest.mark.integration
def test_ntf003_u1_context_pii_never_reaches_title_or_body():
    """NTF-003-U1: values from the event context never leak into title or body."""
    user = UserFactory()

    created = notify(
        user,
        NotificationType.APPLICATION_STATUS,
        {
            "context_url": "/applications/1/",
            "applicant_name": "Sita Karki",
            "project_title": "National ID Rewrite",
            "email": "sita.karki@example.com",
        },
    )

    email_row = Notification.objects.get(recipient=user, channel=Channel.EMAIL)
    for row in (created, email_row):
        assert "Sita Karki" not in row.title
        assert "National ID Rewrite" not in row.title
        assert "sita.karki@example.com" not in row.title
        assert "Sita Karki" not in row.body
        assert "National ID Rewrite" not in row.body
        assert "sita.karki@example.com" not in row.body


@pytest.mark.integration
def test_ntf003_u2_notification_links_to_authenticated_detail():
    """NTF-003-U2: sensitive detail sits behind a platform-relative authenticated link."""
    user = UserFactory()

    created = notify(user, NotificationType.REVIEW_DECISION, {"context_url": "/projects/7/review/"})

    assert created.context_url == "/projects/7/review/"


@pytest.mark.integration
def test_ntf003_external_context_url_is_rejected():
    """NTF-003: only platform-relative detail links are stored; absolute URLs are dropped."""
    user = UserFactory()

    created = notify(user, NotificationType.SECURITY, {"context_url": "https://evil.example.com/x"})

    assert created.context_url == ""


@pytest.mark.integration
def test_ntf003_protocol_relative_context_url_is_rejected():
    """NTF-003: protocol-relative links are external and are not stored as detail links."""
    user = UserFactory()

    created = notify(user, NotificationType.SECURITY, {"context_url": "//evil.example.com/x"})

    assert created.context_url == ""


@pytest.mark.integration
def test_ntf004_u1_failure_is_recorded_with_error_class():
    """NTF-004-U1: a delivery failure is logged on the row with its error class."""
    user = UserFactory()
    email_row = NotificationFactory(
        recipient=user,
        channel=Channel.EMAIL,
        delivery_status=DeliveryStatus.PENDING,
        type=NotificationType.REVIEW_COMMENT,
    )

    record_delivery_failure(email_row, "SMTPRefusedError")

    email_row.refresh_from_db()
    assert email_row.delivery_status == DeliveryStatus.FAILED
    assert email_row.last_error_class == "SMTPRefusedError"
    assert email_row.delivery_attempts == 1
    assert email_row.last_attempt_at is not None


@pytest.mark.integration
def test_ntf004_no_retry_storm_single_retry_flag():
    """NTF-004: a notification is retried at most once and then leaves the retry queue."""
    user = UserFactory()
    email_row = NotificationFactory(
        recipient=user,
        channel=Channel.EMAIL,
        type=NotificationType.REVIEW_COMMENT,
    )

    record_delivery_failure(email_row, "SMTPRefusedError")
    assert email_row in retry_candidates()

    record_delivery_failure(email_row, "SMTPRefusedError")
    assert email_row not in retry_candidates()


@pytest.mark.integration
def test_ntf004_u1_dedup_key_prevents_duplicate_visible_rows():
    """NTF-004-U1: the same dedup key never creates a second user-visible notification."""
    user = UserFactory()

    first = notify(user, NotificationType.REVIEW_COMMENT, {}, dedup_key="contrib:9:verified")
    second = notify(user, NotificationType.REVIEW_COMMENT, {}, dedup_key="contrib:9:verified")

    assert first.pk == second.pk
    assert Notification.objects.filter(recipient=user, channel=Channel.IN_APP).count() == 1
    assert Notification.objects.filter(recipient=user, channel=Channel.EMAIL).count() == 1


@pytest.mark.integration
def test_ntf004_u1_distinct_dedup_keys_create_distinct_rows():
    """NTF-004-U1: different dedup keys produce separate notifications."""
    user = UserFactory()

    notify(user, NotificationType.REVIEW_COMMENT, {}, dedup_key="contrib:9:verified")
    notify(user, NotificationType.REVIEW_COMMENT, {}, dedup_key="contrib:10:verified")

    assert Notification.objects.filter(recipient=user, channel=Channel.IN_APP).count() == 2


@pytest.mark.integration
def test_ntf004_mark_read_is_scoped_and_counted():
    """NTF-004: read state changes only the recipient's own in-app rows."""
    user, other = UserFactory(), UserFactory()
    own_a = NotificationFactory(recipient=user)
    own_b = NotificationFactory(recipient=user)
    foreign = NotificationFactory(recipient=other)

    updated = mark_read(user, [own_a.pk, own_b.pk, foreign.pk])

    assert updated == 2
    own_a.refresh_from_db()
    foreign.refresh_from_db()
    assert own_a.read_at is not None
    assert foreign.read_at is None
    assert unread_count(user) == 0
    assert unread_count(other) == 1


@pytest.mark.integration
@NOTIFICATION_URLCONF
def test_ntf001_i1_member_notification_list_is_authenticated_and_recipient_scoped(client):
    """NTF-001-I1: members see only their own in-app notification feed."""
    member, other = UserFactory(), UserFactory()
    mine = NotificationFactory(recipient=member, title="My notification")
    NotificationFactory(recipient=member, channel=Channel.EMAIL, title="Email notification")
    NotificationFactory(recipient=other, title="Other notification")

    anonymous = client.get(reverse("notifications:list"))
    client.force_login(member)
    response = client.get(reverse("notifications:list"))

    assert anonymous.status_code == 302
    assert anonymous.url.startswith(f"{reverse('accounts:login')}?next=")
    assert response.status_code == 200
    assert response.context["notifications"].get() == mine
    assert b"My notification" in response.content
    assert b"Email notification" not in response.content
    assert b"Other notification" not in response.content


@pytest.mark.integration
@NOTIFICATION_URLCONF
def test_ntf001_i1_member_can_mark_only_own_notification_read_and_audit_it(client):
    """NTF-001-I1: members can mark their own in-app notifications read with an audit record."""
    member, other = UserFactory(), UserFactory()
    own = NotificationFactory(recipient=member)
    foreign = NotificationFactory(recipient=other)
    client.force_login(member)

    forbidden = client.post(reverse("notifications:read", kwargs={"pk": foreign.pk}))
    response = client.post(reverse("notifications:read", kwargs={"pk": own.pk}))

    own.refresh_from_db()
    foreign.refresh_from_db()
    assert forbidden.status_code == 404
    assert response.status_code == 302
    assert response.url == reverse("notifications:list")
    assert own.read_at is not None
    assert foreign.read_at is None
    event = AuditEvent.objects.get(action="notification.mark_read", object_id=str(own.pk))
    assert event.actor == member
    assert event.before == {"read_at": None}
    assert event.after == {"read_at": own.read_at.isoformat()}


@pytest.mark.integration
@NOTIFICATION_URLCONF
def test_ntf001_member_can_mark_all_own_notifications_read(client):
    """NTF-001: members can mark all of their own in-app notifications read at once."""
    member, other = UserFactory(), UserFactory()
    own_a = NotificationFactory(recipient=member)
    own_b = NotificationFactory(recipient=member)
    foreign = NotificationFactory(recipient=other)
    client.force_login(member)

    response = client.post(reverse("notifications:read_all"))

    own_a.refresh_from_db()
    own_b.refresh_from_db()
    foreign.refresh_from_db()
    assert response.status_code == 302
    assert own_a.read_at is not None
    assert own_b.read_at is not None
    assert foreign.read_at is None
    assert AuditEvent.objects.filter(action="notification.mark_read", actor=member).count() == 2
