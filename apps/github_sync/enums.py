from django.db import models
from django.utils.translation import gettext_lazy as _


class Provider(models.TextChoices):
    GITHUB = "github", "GitHub"


class SyncState(models.TextChoices):
    IDLE = "idle", _("Idle")
    SYNCING = "syncing", _("Syncing")
    DEGRADED = "degraded", _("Degraded")
    STOPPED = "stopped", _("Stopped")
    ERROR = "error", _("Error")


class DeliverySource(models.TextChoices):
    WEBHOOK = "webhook", "Webhook"
    RECONCILIATION = "reconciliation", "Reconciliation"


class ProcessingState(models.TextChoices):
    PENDING = "pending", "Pending"
    RECEIVED = "received", "Received"
    QUEUED = "queued", "Queued"
    PROCESSING = "processing", "Processing"
    PROCESSED = "processed", "Processed"
    FAILED = "failed", "Failed"
    DUPLICATE = "duplicate", "Duplicate"
    IGNORED = "ignored", "Ignored"
    REJECTED = "rejected", "Rejected"


class VerifiedEventKind(models.TextChoices):
    """D7/GIT-007: the MVP verified event set. Raw/direct commits are excluded entirely."""

    PR_MERGED = "pr_merged", "Pull request merged"
    ISSUE_COMPLETED = "issue_completed", "Issue completed"
    REVIEW_APPROVED = "review_approved", "Review approved"
    RELEASE_PUBLISHED = "release_published", "Release published"
