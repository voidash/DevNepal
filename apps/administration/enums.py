from django.db import models


class ChangeStatus(models.TextChoices):
    PENDING = "pending", "Awaiting a second Super Admin"
    APPLIED = "applied", "Applied"
    WITHDRAWN = "withdrawn", "Withdrawn"


class GrantAction(models.TextChoices):
    GRANT = "grant", "Grant Super Admin"
    REVOKE = "revoke", "Revoke Super Admin"
