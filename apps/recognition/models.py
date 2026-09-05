import typing
import uuid

from django.db import models
from django.utils.text import get_valid_filename

from apps.recognition.enums import AwardStatus, BadgeKind
from apps.taxonomy.fields import NFCCharField, NFCSlugField, NFCTextField


def badge_icon_path(instance, filename):
    safe_name = get_valid_filename(filename)
    return f"badge-icons/{instance.slug}/{uuid.uuid4().hex}/{safe_name}"


class Badge(models.Model):
    """Badge definition with documented, versioned criteria (REC-007; ADM-001; BR-012)."""

    name = NFCCharField(max_length=100, unique=True)
    slug = NFCSlugField(max_length=120, allow_unicode=True, unique=True)
    description = NFCTextField(blank=True, default="")
    criteria_md = NFCTextField(blank=True, default="")
    criteria_version = models.PositiveIntegerField(default=1)
    kind = models.CharField(
        max_length=12, choices=BadgeKind.choices, default=BadgeKind.CONTRIBUTION
    )
    icon = models.FileField(upload_to=badge_icon_path, null=True, blank=True, max_length=255)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["name"]

    def __str__(self) -> str:
        return self.name


class BadgeAward(models.Model):
    """Badge award with evidence, issuer, and revocation state (REC-004/005/007)."""

    badge = models.ForeignKey(Badge, on_delete=models.PROTECT, related_name="awards")
    recipient = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="badge_awards"
    )
    contribution = models.ForeignKey(
        "contributions.ContributionRecord",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="badge_awards",
    )
    issuer = models.ForeignKey(
        "accounts.User", null=True, on_delete=models.SET_NULL, related_name="issued_badge_awards"
    )
    issued_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=8, choices=AwardStatus.choices, default=AwardStatus.ACTIVE, db_index=True
    )
    revocation_reason = NFCTextField(blank=True, default="")
    revoked_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="revoked_badge_awards",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["-issued_at"]
        constraints: typing.ClassVar[list] = [
            models.UniqueConstraint(
                fields=["badge", "recipient"],
                condition=models.Q(status=AwardStatus.ACTIVE),
                name="uniq_active_award_badge_recipient",
            ),
        ]
        indexes: typing.ClassVar[list] = [
            models.Index(fields=["recipient", "status"], name="idx_award_recipient_status"),
        ]

    def __str__(self) -> str:
        return f"{self.badge.name} → {self.recipient.username}"


class ScoringPolicy(models.Model):
    """Versioned, approved scoring policy; exactly one active row (REC-002; BR-012)."""

    version = models.PositiveIntegerField(unique=True)
    rules = models.JSONField(default=dict)
    document_url = models.URLField(blank=True, default="")
    approved_by = models.ForeignKey(
        "accounts.User",
        null=True,
        on_delete=models.SET_NULL,
        related_name="approved_scoring_policies",
    )
    activated_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["-version"]
        verbose_name = "scoring policy"
        constraints: typing.ClassVar[list] = [
            models.UniqueConstraint(
                fields=["is_active"],
                condition=models.Q(is_active=True),
                name="uniq_active_scoring_policy",
            ),
        ]

    def __str__(self) -> str:
        return f"Scoring policy v{self.version}"


class ContributionScore(models.Model):
    """Points pinned to the policy version that computed them (REC-001/003/005; BR-012)."""

    contribution = models.OneToOneField(
        "contributions.ContributionRecord", on_delete=models.CASCADE, related_name="score"
    )
    policy = models.ForeignKey(ScoringPolicy, on_delete=models.PROTECT, related_name="scores")
    points = models.PositiveIntegerField()
    scored_at = models.DateTimeField(auto_now_add=True)
    reversed_at = models.DateTimeField(null=True, blank=True)
    reversal_reason = NFCTextField(blank=True, default="")

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["-scored_at"]
        indexes: typing.ClassVar[list] = [
            models.Index(fields=["policy", "-points"], name="idx_score_policy_points"),
        ]

    def __str__(self) -> str:
        return f"{self.points} pts for {self.contribution}"
