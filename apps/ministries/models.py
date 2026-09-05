import typing

from django.db import models
from django.utils.translation import get_language

from apps.ministries.enums import (
    ContactChallengeStatus,
    ContactVerificationStatus,
    OrgStatus,
    PublisherStatus,
)
from apps.taxonomy.fields import NFCCharField, NFCSlugField, NFCTextField


class MinistryOrganization(models.Model):
    """Government ministry publisher organization (AUTH-004, GOV-001, BR-001)."""

    name_en = NFCCharField(max_length=200)
    name_ne = NFCTextField(blank=True)
    slug = NFCSlugField(max_length=220, allow_unicode=True, unique=True)
    abbreviation = NFCCharField(max_length=20, blank=True)
    description = NFCTextField(blank=True)
    contact_email = models.EmailField(blank=True)
    website_url = models.URLField(blank=True)
    status = models.CharField(max_length=12, choices=OrgStatus.choices, default=OrgStatus.PENDING)
    provisioned_by = models.ForeignKey(
        "accounts.User",
        null=True,
        on_delete=models.SET_NULL,
        related_name="provisioned_ministries",
    )
    provisioned_at = models.DateTimeField(null=True, blank=True)
    suspended_at = models.DateTimeField(null=True, blank=True)
    suspension_reason = NFCTextField(blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revocation_reason = NFCTextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["name_en", "id"]
        verbose_name = "ministry organization"
        indexes: typing.ClassVar[list] = [
            models.Index(fields=["status"], name="idx_ministry_status")
        ]

    def __str__(self) -> str:
        return self.name_en

    @property
    def localized_name(self) -> str:
        if get_language() == "ne" and self.name_ne:
            return self.name_ne
        return self.name_en


class MinistryPublisher(models.Model):
    """Named officer assignment, independently revocable (AUTH-004, AUTH-005, A1)."""

    user = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="publisher_assignments"
    )
    ministry = models.ForeignKey(
        MinistryOrganization, on_delete=models.CASCADE, related_name="publishers"
    )
    title = NFCCharField(max_length=120)
    official_email = models.EmailField()
    status = models.CharField(
        max_length=10, choices=PublisherStatus.choices, default=PublisherStatus.ACTIVE
    )
    assigned_by = models.ForeignKey(
        "accounts.User",
        null=True,
        on_delete=models.SET_NULL,
        related_name="granted_publisher_roles",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    revoked_by = models.ForeignKey(
        "accounts.User",
        null=True,
        on_delete=models.SET_NULL,
        related_name="revoked_publisher_roles",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    revocation_reason = NFCTextField(blank=True, default="")
    contact_verification_status = models.CharField(
        max_length=10,
        choices=ContactVerificationStatus.choices,
        default=ContactVerificationStatus.PENDING,
    )
    contact_verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["ministry__name_en", "user__username"]
        constraints: typing.ClassVar[list] = [
            models.UniqueConstraint(
                condition=models.Q(status=PublisherStatus.ACTIVE),
                fields=["user", "ministry"],
                name="uniq_active_publisher_user_ministry",
            ),
        ]
        indexes: typing.ClassVar[list] = [
            models.Index(fields=["user", "status"], name="idx_publisher_user_status"),
            models.Index(fields=["ministry", "status"], name="idx_publisher_ministry_status"),
        ]

    def __str__(self) -> str:
        return f"{self.user.username} @ {self.ministry.name_en}"


class OfficialContactChallenge(models.Model):
    """One-time official-contact email challenge (AUTH-005, D3)."""

    publisher = models.ForeignKey(
        MinistryPublisher, on_delete=models.CASCADE, related_name="contact_challenges"
    )
    token_digest = models.CharField(max_length=64, unique=True)
    status = models.CharField(
        max_length=10,
        choices=ContactChallengeStatus.choices,
        default=ContactChallengeStatus.PENDING,
    )
    issued_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    delivered_at = models.DateTimeField(null=True, blank=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    expired_at = models.DateTimeField(null=True, blank=True)
    superseded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["-issued_at", "-id"]
        verbose_name = "official contact challenge"
        indexes: typing.ClassVar[list] = [
            models.Index(fields=["publisher", "status"], name="idx_contact_challenge_state"),
            models.Index(fields=["expires_at"], name="idx_contact_challenge_expiry"),
        ]

    def __str__(self) -> str:
        return f"Contact challenge for {self.publisher} ({self.status})"
