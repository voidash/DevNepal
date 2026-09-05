from django.db import models


class ReportReason(models.TextChoices):
    IMPERSONATION = "impersonation", "Impersonation"
    GOV_BRANDING_MISUSE = "gov_branding_misuse", "Misleading government branding"
    UNSAFE_LINK = "unsafe_link", "Unsafe link"
    MALWARE = "malware", "Malicious file"
    COPYRIGHT = "copyright", "Copyright or intellectual property"
    HARASSMENT = "harassment", "Harassment or code-of-conduct violation"
    SPAM = "spam", "Spam"
    UNLAWFUL_CONTENT = "unlawful_content", "Unlawful content"
    SECURITY_CONCERN = "security_concern", "Security concern"
    OTHER = "other", "Other"


class CaseStatus(models.TextChoices):
    NEW = "new", "New"
    UNDER_REVIEW = "under_review", "Under review"
    ACTION_TAKEN = "action_taken", "Action taken"
    CLOSED_NO_ACTION = "closed_no_action", "Closed - no action"
    APPEALED = "appealed", "Appealed"
    ESCALATED = "escalated", "Escalated"


class ModerationAction(models.TextChoices):
    NO_ACTION = "no_action", "No action"
    WARNING = "warning", "Warning"
    CONTENT_RESTRICTION = "content_restriction", "Content restriction"
    UNPUBLISH = "unpublish", "Unpublish"
    ACCOUNT_SUSPENSION = "account_suspension", "Account suspension"
    ESCALATION = "escalation", "Escalation"


class AppealStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    UPHELD = "upheld", "Upheld"
    OVERTURNED = "overturned", "Overturned"


class CaseEventType(models.TextChoices):
    CREATED = "created", "Created"
    ASSIGNED = "assigned", "Assigned"
    COMMENTED = "commented", "Comment"
    ACTION_TAKEN = "action_taken", "Action taken"
    APPEALED = "appealed", "Appealed"
    ESCALATED = "escalated", "Escalated"
    DECIDED = "decided", "Decided"
    REINSTATED = "reinstated", "Reinstated"
