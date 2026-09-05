from django.db import models
from django.utils.translation import gettext_lazy as _


class OrgStatus(models.TextChoices):
    PENDING = "pending", _("Pending activation")
    ACTIVE = "active", _("Active")
    SUSPENDED = "suspended", _("Suspended")
    REVOKED = "revoked", _("Revoked")


class PublisherStatus(models.TextChoices):
    ACTIVE = "active", _("Active")
    REVOKED = "revoked", _("Revoked")


class ContactVerificationStatus(models.TextChoices):
    PENDING = "pending", _("Pending verification")
    VERIFIED = "verified", _("Verified")


class ContactChallengeStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    COMPLETED = "completed", _("Completed")
    EXPIRED = "expired", _("Expired")
    SUPERSEDED = "superseded", _("Superseded")
