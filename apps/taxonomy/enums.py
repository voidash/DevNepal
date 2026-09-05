from django.db import models


class ContentLanguage(models.TextChoices):
    ENGLISH = "en", "English"
    NEPALI = "ne", "Nepali"


class DataClassification(models.TextChoices):
    PUBLIC = "public", "Public"
    INTERNAL = "internal", "Internal"
    CONFIDENTIAL = "confidential", "Confidential"


class TermVocabulary(models.TextChoices):
    PROJECT_CATEGORY = "project_category", "Project category"
    CONTRIBUTION_TYPE = "contribution_type", "Contribution type"
    TECHNOLOGY = "technology", "Technology"
    EXPERIENCE_BAND = "experience_band", "Experience band"
    TAG = "tag", "Tag"


class SuggestionStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ACCEPTED = "accepted", "Accepted"
    DISMISSED = "dismissed", "Dismissed"
