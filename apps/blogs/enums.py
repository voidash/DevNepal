from django.db import models
from django.utils.translation import gettext_lazy as _


class BlogPostType(models.TextChoices):
    NATIVE = "native", _("DevNepal post")
    EXTERNAL = "external", _("External article")


class BlogStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PUBLISHED = "published", "Published"
    UNPUBLISHED = "unpublished", "Unpublished"
    ARCHIVED = "archived", "Archived"


class BlogModerationState(models.TextChoices):
    NOT_REVIEWED = "not_reviewed", "Not reviewed"
    UNDER_REVIEW = "under_review", "Under review"
    RESTRICTED = "restricted", "Restricted"
    REINSTATED = "reinstated", "Reinstated"
