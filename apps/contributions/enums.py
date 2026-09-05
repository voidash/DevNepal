from django.db import models


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
