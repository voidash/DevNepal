"""Notification entry point for every domain (NTF-001..NTF-004).

Other apps never touch the models directly; they call :func:`notify` and the
read helpers. Email transmission itself is the §10 email-service wave — this
module owns the durable Notification rows and the delivery-state contract.
"""

import dataclasses
import datetime
import itertools
import logging

from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.audit.services import record_audit
from apps.notifications.enums import (
    Channel,
    DeliveryStatus,
    DigestFrequency,
    NotificationType,
    email_category_field,
    is_mandatory,
)
from apps.notifications.models import Notification, NotificationPreference

logger = logging.getLogger(__name__)

MAX_DELIVERY_ATTEMPTS = 2

PREFERENCE_FIELDS = (
    "email_applications",
    "email_reviews",
    "email_contributions",
    "email_community",
    "digest_frequency",
)

DEFAULT_GENERIC_SUBJECT = _("You have a new notification on DevNepal")
GENERIC_SUBJECTS = {
    NotificationType.APPLICATION_STATUS: _("You have a new notification on DevNepal"),
    NotificationType.REVIEW_DECISION: _("You have a new notification on DevNepal"),
    NotificationType.REVIEW_COMMENT: _("You have a new notification on DevNepal"),
    NotificationType.ASSIGNMENT: _("You have a new notification on DevNepal"),
    NotificationType.CONTRIBUTION_VERIFIED: _("You have a new notification on DevNepal"),
    NotificationType.CONTRIBUTION_REVOKED: _("You have a new notification on DevNepal"),
    NotificationType.BADGE_AWARDED: _("You have a new notification on DevNepal"),
    NotificationType.PROJECT_UPDATE: _("You have a new notification on DevNepal"),
    NotificationType.PROJECT_STATUS: _("You have a new notification on DevNepal"),
    NotificationType.BOOKMARK_CHANGE: _("You have a new notification on DevNepal"),
    NotificationType.MODERATION: _("Important notice about your DevNepal account"),
    NotificationType.SECURITY: _("Important notice about your DevNepal account"),
    NotificationType.ACCOUNT: _("Important notice about your DevNepal account"),
}

GENERIC_BODY = _("Sign in to DevNepal to view the details.")
TEMPLATE_VERSION = "generic-v1"


class UnknownNotificationType(ValueError):
    """notify() was called with a value outside NotificationType."""


def safe_subject(type_: str) -> str:
    """Return the allowlisted generic subject for a type (NTF-003).

    Subjects never interpolate event context; sensitive detail lives behind
    the authenticated ``context_url`` only.
    """
    return str(GENERIC_SUBJECTS.get(type_, DEFAULT_GENERIC_SUBJECT))


def _sanitize_context_url(context: dict) -> str:
    raw = str(context.get("context_url") or "")
    if raw and (not raw.startswith("/") or raw.startswith("//")):
        logger.warning("notify(): dropped non-platform context_url %r", raw)
        return ""
    return raw[:500]


def _resolve_email_status(user, type_: str, mandatory: bool) -> str:
    if mandatory or is_mandatory(type_):
        return DeliveryStatus.PENDING
    preference = preferences_for(user)
    category_field = email_category_field(type_)
    if category_field is None:
        return DeliveryStatus.PENDING
    if not getattr(preference, category_field):
        return DeliveryStatus.SUPPRESSED
    return DeliveryStatus.PENDING


def preferences_for(user) -> NotificationPreference:
    """The member's email preferences, created with platform defaults (NTF-002)."""
    preference, _created = NotificationPreference.objects.get_or_create(user=user)
    return preference


def _preference_state(preference: NotificationPreference) -> dict:
    return {field: getattr(preference, field) for field in PREFERENCE_FIELDS}


def update_email_preferences(user, **fields) -> NotificationPreference:
    """Persist a member's own email-category toggles with an audit record (NTF-002).

    Mandatory security/administrative notices are not represented here and stay
    locked on in the delivery layer.
    """
    preference = preferences_for(user)
    before = _preference_state(preference)
    for field, value in fields.items():
        if field not in PREFERENCE_FIELDS:
            raise ValueError(f"unknown preference field {field!r}")
        setattr(preference, field, value)
    preference.save()
    record_audit(
        actor=user,
        action="notification.preferences_update",
        obj=preference,
        before=before,
        after=_preference_state(preference),
    )
    return preference


def _scoped_dedup_key(dedup_key: str | None, channel: str) -> str:
    if dedup_key is None:
        return ""
    return dedup_key if channel == Channel.IN_APP else f"email:{dedup_key}"


def _email_subject(type_: str, email_subject: str | None) -> str:
    generic = safe_subject(type_)
    if email_subject is None:
        return generic
    if email_subject in {str(subject) for subject in GENERIC_SUBJECTS.values()}:
        return email_subject
    logger.warning(
        "notify(): rejected non-generic email_subject for type=%s; generic subject used",
        type_,
    )
    return generic


def notify(
    user,
    type: str,
    context: dict,
    *,
    email_subject: str | None = None,
    mandatory: bool = False,
    dedup_key: str | None = None,
) -> Notification:
    """Record a workflow event for one recipient (NTF-001).

    Always creates the in-app row. Creates a second email row that is PENDING
    (queued), or SUPPRESSED when a non-essential category is opted out
    (NTF-002); mandatory security/administrative types ignore preferences.
    Returns the in-app row. ``dedup_key`` makes repeated delivery of the same
    event idempotent per channel (NTF-004).
    """
    if type not in NotificationType.values:
        raise UnknownNotificationType(type)

    context_url = _sanitize_context_url(context)
    subject = _email_subject(type, email_subject)
    common = {
        "type": type,
        "title": subject,
        "body": str(GENERIC_BODY),
        "context_url": context_url,
        "template_version": TEMPLATE_VERSION,
    }

    in_app_key = _scoped_dedup_key(dedup_key, Channel.IN_APP)
    email_key = _scoped_dedup_key(dedup_key, Channel.EMAIL)
    email_status = _resolve_email_status(user, type, mandatory)

    try:
        with transaction.atomic():
            in_app_row = Notification.objects.create(
                recipient=user,
                channel=Channel.IN_APP,
                delivery_status=DeliveryStatus.DELIVERED,
                dedup_key=in_app_key,
                **common,
            )
            Notification.objects.create(
                recipient=user,
                channel=Channel.EMAIL,
                delivery_status=email_status,
                dedup_key=email_key,
                **common,
            )
    except IntegrityError:
        logger.info(
            "notify(): deduplicated type=%s dedup_key=%r for user=%s", type, dedup_key, user
        )
        in_app_row = Notification.objects.get(recipient=user, dedup_key=in_app_key)
    return in_app_row


def notifications_for(user):
    """Recipient-scoped in-app feed queryset (NTF-001-I1)."""
    return Notification.objects.filter(recipient=user, channel=Channel.IN_APP)


def unread_count(user) -> int:
    return Notification.objects.filter(
        recipient=user, channel=Channel.IN_APP, read_at__isnull=True
    ).count()


def mark_read(user, notification_ids) -> int:
    """Mark the recipient's own unread in-app rows read and record each state change."""
    notifications = list(
        notifications_for(user).filter(id__in=notification_ids, read_at__isnull=True).only("pk")
    )
    if not notifications:
        return 0

    read_at = timezone.now()
    Notification.objects.filter(pk__in=[notification.pk for notification in notifications]).update(
        read_at=read_at
    )
    for notification in notifications:
        record_audit(
            actor=user,
            action="notification.mark_read",
            obj=notification,
            before={"read_at": None},
            after={"read_at": read_at.isoformat()},
        )
    return len(notifications)


def record_delivery_failure(notification: Notification, error_class: str) -> None:
    """Record one failed delivery attempt with its error class (NTF-004)."""
    notification.delivery_status = DeliveryStatus.FAILED
    notification.last_error_class = error_class[:100]
    notification.delivery_attempts = min(notification.delivery_attempts + 1, MAX_DELIVERY_ATTEMPTS)
    notification.last_attempt_at = timezone.now()
    notification.save(
        update_fields=[
            "delivery_status",
            "last_error_class",
            "delivery_attempts",
            "last_attempt_at",
        ]
    )


def retry_candidates():
    """Failed email rows still allowed their single retry (NTF-004)."""
    return Notification.objects.filter(
        channel=Channel.EMAIL,
        delivery_status=DeliveryStatus.FAILED,
        delivery_attempts__lt=MAX_DELIVERY_ATTEMPTS,
    )


def digest_cutoff(frequency: str, now: datetime.datetime) -> datetime.datetime:
    """Window start for a digest at ``now`` (frozen-clock testable, NTF-002)."""
    if frequency == DigestFrequency.DAILY:
        return now - datetime.timedelta(days=1)
    if frequency == DigestFrequency.WEEKLY:
        return now - datetime.timedelta(weeks=1)
    raise ValueError(f"no digest window for frequency {frequency!r}")


def collect_digest(user):
    """Pending email rows grouped into this user's current digest (NTF-002)."""
    preference = preferences_for(user)
    if preference.digest_frequency == DigestFrequency.NONE:
        return Notification.objects.none()
    digestible_types = [
        value
        for value in NotificationType.values
        if (field := email_category_field(value)) is not None and getattr(preference, field)
    ]
    return Notification.objects.filter(
        recipient=user,
        channel=Channel.EMAIL,
        delivery_status=DeliveryStatus.PENDING,
        type__in=digestible_types,
        created_at__gte=digest_cutoff(preference.digest_frequency, timezone.now()),
    )


@dataclasses.dataclass(frozen=True)
class DispatchResult:
    sent: int
    failed: int
    suppressed: int


def _dispatch_candidates():
    return (
        Notification.objects.filter(channel=Channel.EMAIL)
        .filter(
            Q(delivery_status=DeliveryStatus.PENDING)
            | Q(
                delivery_status=DeliveryStatus.FAILED,
                delivery_attempts__lt=MAX_DELIVERY_ATTEMPTS,
            )
        )
        .select_related("recipient")
        .order_by("recipient_id", "pk")
    )


def _allows_email(type_: str, preference: NotificationPreference) -> bool:
    if is_mandatory(type_):
        return True
    category_field = email_category_field(type_)
    if category_field is None:
        return True
    return bool(getattr(preference, category_field))


def _compose_subject(rows: list[Notification]) -> str:
    subjects = {safe_subject(row.type) for row in rows}
    if len(subjects) == 1:
        return subjects.pop()
    return str(DEFAULT_GENERIC_SUBJECT)


def _compose_body(rows: list[Notification]) -> str:
    return "\n\n".join(f"{row.title}\n{row.context_url}".strip() for row in rows)


def _mark_sent(rows: list[Notification], when: datetime.datetime) -> int:
    for row in rows:
        row.delivery_status = DeliveryStatus.SENT
        row.last_attempt_at = when
        row.last_error_class = ""
        row.save(update_fields=["delivery_status", "last_attempt_at", "last_error_class"])
    return len(rows)


def _deliver(rows: list[Notification]) -> tuple[int, int]:
    """Send one generic-subject email covering ``rows``; returns (sent, failed) rows.

    Subjects come only from the NTF-003 allowlist and bodies only from the stored
    generic title plus the internal platform-relative URL — never event context.
    """
    if not rows:
        return 0, 0
    try:
        send_mail(
            subject=_compose_subject(rows),
            message=_compose_body(rows),
            from_email=None,
            recipient_list=[rows[0].recipient.email],
            fail_silently=False,
        )
    except Exception as exc:
        logger.exception(
            "send_pending_notifications: delivery failed for rows %s",
            [row.pk for row in rows],
        )
        for row in rows:
            record_delivery_failure(row, type(exc).__name__)
        return 0, len(rows)
    return _mark_sent(rows, timezone.now()), 0


def send_pending_notifications() -> DispatchResult:
    """Deliver queued notification emails exactly once (NTF-002/NTF-003/NTF-004).

    Drains PENDING email rows plus FAILED rows inside the retry budget. Rows
    whose category the member has since opted out are flipped SUPPRESSED; the
    digest frequency groups a member's rows into one email. In-app rows are
    never touched. Idempotent: sent rows leave the queue.
    """
    sent = failed = suppressed = 0
    for _recipient_id, group in itertools.groupby(
        _dispatch_candidates(), key=lambda row: row.recipient_id
    ):
        rows = list(group)
        preference = preferences_for(rows[0].recipient)
        allowed, opted_out_pks = [], []
        for row in rows:
            if _allows_email(row.type, preference):
                allowed.append(row)
            else:
                opted_out_pks.append(row.pk)
        if opted_out_pks:
            suppressed += Notification.objects.filter(pk__in=opted_out_pks).update(
                delivery_status=DeliveryStatus.SUPPRESSED
            )
        if not allowed:
            continue
        if preference.digest_frequency == DigestFrequency.NONE:
            for row in allowed:
                row_sent, row_failed = _deliver([row])
                sent += row_sent
                failed += row_failed
        else:
            digest_sent, digest_failed = _deliver(allowed)
            sent += digest_sent
            failed += digest_failed
    return DispatchResult(sent=sent, failed=failed, suppressed=suppressed)
