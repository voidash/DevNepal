from django.db import models
from django.utils.translation import gettext_lazy as _


class ContributionSource(models.TextChoices):
    PROVIDER_EVENT = "provider_event", "Authoritative provider event"
    MAINTAINER_ATTESTATION = "maintainer_attestation", "Maintainer attestation"
    MEMBER_SUBMISSION = "member_submission", "Member-submitted evidence"


class VerificationStatus(models.TextChoices):
    CANDIDATE = "candidate", "Candidate"
    PENDING_INFO = "pending_info", "Clarification requested"
    ACCEPTED = "accepted", "Accepted"
    REJECTED = "rejected", "Rejected"
    REVOKED = "revoked", "Revoked"


class ImpactTier(models.TextChoices):
    MINOR = "minor", "Minor"
    STANDARD = "standard", "Standard"
    MAJOR = "major", "Major"


class EvidenceScanStatus(models.TextChoices):
    NOT_APPLICABLE = "not_applicable", _("No file submitted")
    PENDING = "pending", _("Pending security check")
    CLEAN = "clean", _("Security check passed")
    QUARANTINED = "quarantined", _("Quarantined")
    FAILED = "failed", _("Security check failed")
