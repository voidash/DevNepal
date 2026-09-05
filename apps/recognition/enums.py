from django.db import models
from django.utils.translation import gettext_lazy as _


class BadgeKind(models.TextChoices):
    CONTRIBUTION = "contribution", _("Contribution")
    MILESTONE = "milestone", _("Milestone")
    COMMUNITY = "community", _("Community")
    SPECIAL = "special", _("Special")


class AwardStatus(models.TextChoices):
    ACTIVE = "active", _("Active")
    REVOKED = "revoked", _("Revoked")


class CorrectionKind(models.TextChoices):
    CONSOLIDATE = "consolidate", _("Consolidate")
    RELEASE_HELD = "release_held", _("Release held")
    INVALIDATE = "invalidate", _("Invalidate")
    ADJUST_SCORE = "adjust_score", _("Adjust score")


class CorrectionReason(models.TextChoices):
    DUPLICATE_TRIVIAL_BATCH = "duplicate_trivial_batch", _("Batch of trivial changes")
    EVIDENCE_REASSESSMENT = "evidence_reassessment", _("Evidence reassessment")
    MAINTAINER_CORRECTION = "maintainer_correction", _("Maintainer correction")
    INVALID_SOURCE = "invalid_source", _("Invalid or duplicate source")
    SCORE_CALCULATION_ERROR = "score_calculation_error", _("Score calculation error")
    HOLD_RESOLVED = "hold_resolved", _("Outcome hold resolved")


class CorrectionStatus(models.TextChoices):
    APPLIED = "applied", _("Applied")
    APPEALED = "appealed", _("Appealed")
    UPHELD = "upheld", _("Upheld")
    OVERTURNED = "overturned", _("Overturned")


class LeaderboardScope(models.TextChoices):
    ROLLING = "rolling", _("Rolling period")
    ANNUAL = "annual", _("Annual")
    MINISTRY = "ministry", _("Ministry")
    PROJECT = "project", _("Project")
    CONTRIBUTION_TYPE = "contribution_type", _("Contribution type")
    LIFETIME = "lifetime", _("Lifetime")
