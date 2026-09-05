from django.db import models


class NotificationType(models.TextChoices):
    APPLICATION_STATUS = "application_status", "Application status"
    REVIEW_DECISION = "review_decision", "Review decision"
    REVIEW_COMMENT = "review_comment", "Review comment"
    ASSIGNMENT = "assignment", "Work assignment"
    CONTRIBUTION_VERIFIED = "contribution_verified", "Contribution verified"
    CONTRIBUTION_REVOKED = "contribution_revoked", "Contribution revoked"
    BADGE_AWARDED = "badge_awarded", "Badge awarded"
    PROJECT_UPDATE = "project_update", "Project update"
    PROJECT_STATUS = "project_status", "Project status change"
    BOOKMARK_CHANGE = "bookmark_change", "Bookmarked project changed"
    MODERATION = "moderation", "Moderation"
    SECURITY = "security", "Security"
    ACCOUNT = "account", "Account"


class Channel(models.TextChoices):
    IN_APP = "in_app", "In-app"
    EMAIL = "email", "Email"


class DeliveryStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SENT = "sent", "Sent"
    DELIVERED = "delivered", "Delivered"
    FAILED = "failed", "Failed"
    SUPPRESSED = "suppressed", "Suppressed"


class DigestFrequency(models.TextChoices):
    NONE = "none", "No digest"
    DAILY = "daily", "Daily"
    WEEKLY = "weekly", "Weekly"


MANDATORY_NOTIFICATION_TYPES = frozenset(
    {NotificationType.SECURITY, NotificationType.ACCOUNT, NotificationType.MODERATION}
)

EMAIL_CATEGORY_FIELD_BY_TYPE = {
    NotificationType.APPLICATION_STATUS: "email_applications",
    NotificationType.ASSIGNMENT: "email_applications",
    NotificationType.REVIEW_DECISION: "email_reviews",
    NotificationType.REVIEW_COMMENT: "email_reviews",
    NotificationType.CONTRIBUTION_VERIFIED: "email_contributions",
    NotificationType.CONTRIBUTION_REVOKED: "email_contributions",
    NotificationType.BADGE_AWARDED: "email_community",
    NotificationType.PROJECT_UPDATE: "email_community",
    NotificationType.PROJECT_STATUS: "email_community",
    NotificationType.BOOKMARK_CHANGE: "email_community",
}


def is_mandatory(type_: str) -> bool:
    return type_ in MANDATORY_NOTIFICATION_TYPES


def email_category_field(type_: str) -> str | None:
    return EMAIL_CATEGORY_FIELD_BY_TYPE.get(type_)
