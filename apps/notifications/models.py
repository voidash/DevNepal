import typing

from django.db import models

from apps.notifications.enums import Channel, DeliveryStatus, DigestFrequency, NotificationType
from apps.taxonomy.fields import NFCCharField, NFCTextField


class Notification(models.Model):
    """Single delivery of a workflow event to one recipient over one channel.

    In-app and email copies are separate rows so read state, delivery status,
    and retries (NTF-004) are tracked per channel.
    """

    recipient = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="notifications"
    )
    type = models.CharField(max_length=25, choices=NotificationType.choices, db_index=True)
    channel = models.CharField(max_length=8, choices=Channel.choices, default=Channel.IN_APP)
    title = NFCCharField(max_length=200)
    body = NFCTextField(blank=True, default="")
    context_url = models.CharField(max_length=500, blank=True, default="")
    read_at = models.DateTimeField(null=True, blank=True, db_index=True)
    delivery_status = models.CharField(
        max_length=10, choices=DeliveryStatus.choices, default=DeliveryStatus.PENDING, db_index=True
    )
    template_version = models.CharField(max_length=20, blank=True, default="")
    delivery_attempts = models.PositiveSmallIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    last_error_class = models.CharField(max_length=100, blank=True, default="")
    dedup_key = models.CharField(max_length=120, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["-created_at"]
        indexes: typing.ClassVar[list] = [
            models.Index(fields=["recipient", "read_at"], name="idx_notif_recipient_read"),
            models.Index(fields=["delivery_status"], name="idx_notif_delivery_status"),
        ]
        constraints: typing.ClassVar[list] = [
            models.UniqueConstraint(
                fields=["recipient", "dedup_key"],
                condition=~models.Q(dedup_key=""),
                name="uniq_notif_recipient_dedup",
            ),
        ]

    def __str__(self):
        return f"{self.get_type_display()} to {self.recipient.username}"


class NotificationPreference(models.Model):
    """User-controlled, non-essential email switches (NTF-002).

    Mandatory security/administrative notices bypass these switches in the
    service layer and cannot be disabled.
    """

    user = models.OneToOneField(
        "accounts.User", on_delete=models.CASCADE, related_name="notification_preferences"
    )
    email_applications = models.BooleanField(default=True)
    email_reviews = models.BooleanField(default=True)
    email_contributions = models.BooleanField(default=True)
    email_community = models.BooleanField(default=False)
    digest_frequency = models.CharField(
        max_length=8, choices=DigestFrequency.choices, default=DigestFrequency.NONE
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["user_id"]
        verbose_name = "notification preference"

    def __str__(self):
        return f"Preferences for {self.user.username}"
