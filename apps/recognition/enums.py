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


class LeaderboardScope(models.TextChoices):
    ROLLING = "rolling", _("Rolling period")
    ANNUAL = "annual", _("Annual")
    MINISTRY = "ministry", _("Ministry")
    PROJECT = "project", _("Project")
    CONTRIBUTION_TYPE = "contribution_type", _("Contribution type")
    LIFETIME = "lifetime", _("Lifetime")
