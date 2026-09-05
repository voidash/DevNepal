import typing

from django.db import models
from django.utils import timezone

from apps.administration.enums import ChangeStatus, GrantAction
from apps.taxonomy.fields import NFCCharField, NFCTextField


class FeatureFlag(models.Model):
    """ADM-001/D5.7: a scoped, owned, reasoned switch over an open platform decision."""

    key = models.SlugField(max_length=100, unique=True)
    label = NFCCharField(max_length=200)
    description = NFCTextField(blank=True, default="")
    scope = NFCCharField(max_length=120, default="Everyone")
    owner = NFCCharField(max_length=120, blank=True, default="")
    reason = NFCTextField(blank=True, default="")
    affects_members = models.BooleanField(default=False)
    is_enabled = models.BooleanField(default=False)
    version = models.PositiveIntegerField(default=0)
    updated_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="feature_flag_changes",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["key"]
        verbose_name = "feature flag"
        verbose_name_plural = "feature flags"

    def __str__(self) -> str:
        return f"{self.key} ({'on' if self.is_enabled else 'off'})"

    @property
    def requires_four_eyes(self) -> bool:
        """D5.7: a switch that changes what members see needs a second Super Admin."""
        return self.affects_members


class FeatureFlagChange(models.Model):
    """D5.7/ADM-008: one versioned, attributed configuration change to a switch.

    Every change is recorded here whether or not it needed a second approver, so
    the change log can state who proposed it, why, and who confirmed it.
    """

    flag = models.ForeignKey(FeatureFlag, on_delete=models.CASCADE, related_name="changes")
    version = models.PositiveIntegerField()
    from_enabled = models.BooleanField()
    to_enabled = models.BooleanField()
    reason = NFCTextField()
    status = models.CharField(
        max_length=12, choices=ChangeStatus.choices, default=ChangeStatus.PENDING
    )
    proposed_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="proposed_flag_changes"
    )
    proposed_at = models.DateTimeField(auto_now_add=True)
    approved_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="approved_flag_changes",
    )
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["-proposed_at", "-id"]
        verbose_name = "feature flag change"
        verbose_name_plural = "feature flag changes"
        constraints: typing.ClassVar[list] = [
            models.UniqueConstraint(fields=["flag", "version"], name="uniq_flagchange_version"),
        ]
        indexes: typing.ClassVar[list] = [
            models.Index(fields=["status", "proposed_at"], name="idx_flagchange_status"),
        ]

    def __str__(self) -> str:
        return f"{self.flag.key} v{self.version} ({self.status})"

    @property
    def is_four_eyes(self) -> bool:
        return bool(self.approved_by_id and self.approved_by_id != self.proposed_by_id)


class SuperAdminGrant(models.Model):
    """AUTH-003/D5.8: a proposed change to who holds Super Admin, and who confirmed it.

    A grant is never one person's decision: it is proposed, then confirmed by a
    different Super Admin within a fixed window. A revocation is immediate, and
    the revoked person's audit entries stay under their own name.
    """

    subject = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="super_admin_grants"
    )
    action = models.CharField(max_length=8, choices=GrantAction.choices)
    reason = NFCTextField()
    status = models.CharField(
        max_length=12, choices=ChangeStatus.choices, default=ChangeStatus.PENDING
    )
    proposed_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="proposed_super_admin_grants"
    )
    proposed_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    approved_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="approved_super_admin_grants",
    )
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["-proposed_at", "-id"]
        verbose_name = "super admin grant"
        verbose_name_plural = "super admin grants"
        indexes: typing.ClassVar[list] = [
            models.Index(fields=["status", "expires_at"], name="idx_grant_status_expiry"),
        ]

    def __str__(self) -> str:
        return f"{self.get_action_display()} for {self.subject.username} ({self.status})"

    def has_expired(self, *, now=None) -> bool:
        return (now or timezone.now()) >= self.expires_at
