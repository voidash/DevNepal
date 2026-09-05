import typing

from django.core.validators import URLValidator
from django.db import models

from apps.accounts.services import normalize_public_url


class NormalizedURLField(models.URLField):
    """Member-facing URL field: http/https only at clean time, normalized before save (MEM-007)."""

    default_validators: typing.ClassVar[list] = [URLValidator(schemes=["http", "https"])]

    def get_prep_value(self, value):
        return normalize_public_url(super().get_prep_value(value))
