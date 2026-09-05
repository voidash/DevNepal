from django.db import models
from django.utils.translation import gettext_lazy as _


class ProjectType(models.TextChoices):
    GOVERNMENT = "government", _("Government")
    PERSONAL = "personal", _("Personal (community)")


class ProjectStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    IN_REVIEW = "in_review", _("In review")
    CHANGES_REQUESTED = "changes_requested", _("Changes requested")
    APPROVED = "approved", _("Approved / scheduled")
    OPEN_FOR_CONTRIBUTION = "open_for_contribution", _("Open for contribution")
    PAUSED = "paused", _("Paused")
    COMPLETED = "completed", _("Completed")
    CANCELLED = "cancelled", _("Cancelled")
    ARCHIVED = "archived", _("Archived")


class DifficultyLevel(models.TextChoices):
    BEGINNER = "beginner", _("Beginner")
    INTERMEDIATE = "intermediate", _("Intermediate")
    ADVANCED = "advanced", _("Advanced")


class EffortBand(models.TextChoices):
    SMALL = "small", _("Small (about 1 week)")
    MEDIUM = "medium", _("Medium (1-4 weeks)")
    LARGE = "large", _("Large (over 4 weeks)")


class ContributionMode(models.TextChoices):
    OPEN_DIRECT = "open_direct", _("Open direct contribution")
    APPLICATION = "application", _("Application required")
    HYBRID = "hybrid", _("Hybrid (open tasks and application workstreams)")


class ResponseSla(models.TextChoices):
    WITHIN_24_HOURS = "24h", _("Within 24 hours")
    WITHIN_3_DAYS = "3d", _("Within 3 days")
    WITHIN_1_WEEK = "1w", _("Within 1 week")


class GovernanceModel(models.TextChoices):
    MAINTAINER_CONSENSUS = "maintainer_consensus", _("Maintainer consensus")
    LEAD_MAINTAINER = "lead_maintainer", _("Lead maintainer decides")
    MINISTRY_APPROVAL = "ministry_approval", _("Ministry approval required")


class SignoffModel(models.TextChoices):
    DCO = "dco", _("DCO-style sign-off")
    CLA = "cla", _("CLA required")
    NONE_REQUIRED = "none", _("None required (non-code)")


class MaintainerRole(models.TextChoices):
    LEAD = "lead", _("Lead maintainer")
    MAINTAINER = "maintainer", _("Maintainer")
    REVIEWER = "reviewer", _("Reviewer")


class AttachmentKind(models.TextChoices):
    PROPOSAL = "proposal", _("Proposal")
    REQUIREMENTS = "requirements", _("Requirements")
    ARCHITECTURE = "architecture", _("Architecture")
    DESIGN = "design", _("Design")
    API_DOC = "api_doc", _("API documentation")
    RESEARCH = "research", _("Research")
    TERMS = "terms", _("Terms")
    IMAGE = "image", _("Image")
    OTHER = "other", _("Other")


class ScanStatus(models.TextChoices):
    PENDING = "pending", _("Pending scan")
    CLEAN = "clean", _("Clean")
    QUARANTINED = "quarantined", _("Quarantined")
    FAILED = "failed", _("Scan failed")


class ReviewDecision(models.TextChoices):
    APPROVED = "approved", _("Approved")
    CHANGES_REQUESTED = "changes_requested", _("Changes requested")
    REJECTED = "rejected", _("Rejected")
    PUBLISHED = "published", _("Published")
    REVOKED = "revoked", _("Approval revoked")
    RESTORED = "restored", _("Restored from archive")


class ParticipationKind(models.TextChoices):
    INTEREST = "interest", _("Expressed interest")
    APPLICATION = "application", _("Application")
    ASSIGNMENT = "assignment", _("Assigned work")


class ApplicationStatus(models.TextChoices):
    SUBMITTED = "submitted", _("Submitted")
    INFO_REQUESTED = "info_requested", _("Information requested")
    WAITLISTED = "waitlisted", _("Waitlisted")
    ACCEPTED = "accepted", _("Accepted")
    DECLINED = "declined", _("Declined")
    WITHDRAWN = "withdrawn", _("Withdrawn")


class ApplicationEventType(models.TextChoices):
    SUBMITTED = "submitted", _("Submitted")
    STATUS_CHANGED = "status_changed", _("Status changed")
    INFO_REQUESTED = "info_requested", _("Information requested")
    INFO_PROVIDED = "info_provided", _("Information provided")
    COMMENTED = "commented", _("Comment")
    ASSIGNED = "assigned", _("Work assigned")
    WITHDRAWN = "withdrawn", _("Withdrawn")


class TaskStatus(models.TextChoices):
    OPEN = "open", _("Open")
    ASSIGNED = "assigned", _("Assigned")
    IN_PROGRESS = "in_progress", _("In progress")
    DONE = "done", _("Done")
    CANCELLED = "cancelled", _("Cancelled")


class MilestoneStatus(models.TextChoices):
    PLANNED = "planned", _("Planned")
    IN_PROGRESS = "in_progress", _("In progress")
    ACHIEVED = "achieved", _("Achieved")
    DROPPED = "dropped", _("Dropped")


class UpdateKind(models.TextChoices):
    PROGRESS = "progress", _("Progress")
    MILESTONE = "milestone", _("Milestone")
    RELEASE = "release", _("Release/result")
    COMPLETION = "completion", _("Completion summary")


class ProjectLinkKind(models.TextChoices):
    REPOSITORY = "repository", _("Repository")
    DEMO = "demo", _("Demo")
    WEBSITE = "website", _("Website")
    DOCUMENTATION = "documentation", _("Documentation")
    ARTICLE = "article", _("Article")
    OTHER = "other", _("Other")


class OwnershipVerificationStatus(models.TextChoices):
    UNVERIFIED = "unverified", _("Unverified")
    VERIFIED_GITHUB = "verified_github", _("Verified via GitHub")
    VERIFIED_DOMAIN = "verified_domain", _("Verified via domain")
    VERIFIED_MANUAL = "verified_manual", _("Verified manually by Super Admin")
