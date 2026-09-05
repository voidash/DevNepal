import typing
import uuid

from django.db import models
from django.utils.text import get_valid_filename

from apps.contributions.enums import ContributionSource, ImpactTier, VerificationStatus
from apps.taxonomy.fields import NFCCharField, NFCTextField


def evidence_upload_path(instance, filename):
    safe_name = get_valid_filename(filename)
    return f"contribution-evidence/{uuid.uuid4().hex}/{safe_name}"


class ContributionRecord(models.Model):
    """Verified contribution record (§9.1; §6.2 steps 5-7; BR-006, BR-008; REC-001, REC-008)."""

    project = models.ForeignKey(
        "projects.Project", on_delete=models.PROTECT, related_name="contributions"
    )
    contributor = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="contributions",
    )
    contribution_type = models.ForeignKey(
        "taxonomy.TaxonomyTerm", on_delete=models.PROTECT, related_name="contributions"
    )
    title = NFCCharField(max_length=200)
    description = NFCTextField(blank=True, default="")
    evidence_url = models.URLField(blank=True, default="")
    evidence_file = models.FileField(
        upload_to=evidence_upload_path, null=True, blank=True, max_length=255
    )
    source = models.CharField(
        max_length=25,
        choices=ContributionSource.choices,
        default=ContributionSource.MEMBER_SUBMISSION,
    )
    provider_event_ref = models.CharField(max_length=120, blank=True, default="")
    status = models.CharField(
        max_length=15,
        choices=VerificationStatus.choices,
        default=VerificationStatus.CANDIDATE,
        db_index=True,
    )
    impact_tier = models.CharField(
        max_length=10, choices=ImpactTier.choices, default=ImpactTier.STANDARD
    )
    verified_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="verified_contributions",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    verification_note = NFCTextField(blank=True, default="")
    secondary_approval_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="secondary_approvals",
    )
    pending_mapping = models.BooleanField(default=False)
    hold_active = models.BooleanField(default=False)
    held_from_status = models.CharField(
        max_length=15,
        choices=VerificationStatus.choices,
        blank=True,
        default="",
    )
    hold_reason = NFCTextField(blank=True, default="")
    held_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="held_contributions",
    )
    held_at = models.DateTimeField(null=True, blank=True)
    hold_released_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="released_contribution_holds",
    )
    hold_released_at = models.DateTimeField(null=True, blank=True)
    hold_release_reason = NFCTextField(blank=True, default="")
    hold_response = NFCTextField(blank=True, default="")
    hold_responded_at = models.DateTimeField(null=True, blank=True)
    revocation_reason = NFCTextField(blank=True, default="")
    revoked_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="revoked_contributions",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["-verified_at", "-created_at"]
        constraints: typing.ClassVar[list] = [
            models.UniqueConstraint(
                fields=["provider_event_ref"],
                condition=~models.Q(provider_event_ref=""),
                name="uniq_contrib_provider_event_ref",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(hold_active=True)
                    | (
                        models.Q(
                            held_at__isnull=False,
                            held_by__isnull=False,
                            held_from_status__in=(
                                VerificationStatus.CANDIDATE,
                                VerificationStatus.PENDING_INFO,
                            ),
                            hold_active=True,
                        )
                        & ~models.Q(hold_reason="")
                    )
                ),
                name="contrib_hold_metadata_consistent",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(hold_responded_at__isnull=True, hold_response="")
                    | (models.Q(hold_responded_at__isnull=False) & ~models.Q(hold_response=""))
                ),
                name="contrib_hold_response_consistent",
            ),
        ]
        indexes: typing.ClassVar[list] = [
            models.Index(fields=["project", "status"], name="idx_contrib_project_status"),
            models.Index(fields=["contributor", "status"], name="idx_contrib_contributor_status"),
            models.Index(fields=["status", "-verified_at"], name="idx_contrib_status_verified"),
            models.Index(
                fields=["contribution_type", "-verified_at"], name="idx_contrib_type_verified"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.title} by {self.contributor}"

    @property
    def has_recorded_automated_check(self) -> bool:
        """True only when an authoritative provider event reference was persisted."""
        return bool(self.source == ContributionSource.PROVIDER_EVENT and self.provider_event_ref)
