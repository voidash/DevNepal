from django.db import models


class EventName(models.TextChoices):
    PROJECT_VIEWED = "project_viewed", "Project viewed"
    PROJECT_APPLIED = "project_applied", "Project application submitted"
    CONTRIBUTION_ACCEPTED = "contribution_accepted", "Contribution accepted"
