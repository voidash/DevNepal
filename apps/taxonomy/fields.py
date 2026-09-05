import unicodedata

from django.db import models


def normalize_nfc(value: str) -> str:
    """Compose user text to NFC and strip edge whitespace (DSC-003).

    Non-string values (e.g. ``None`` from empty fields) pass through unchanged so
    field ``get_prep_value`` chains stay safe.
    """
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value).strip()
    return value


class NFCCharField(models.CharField):
    def get_prep_value(self, value):
        return normalize_nfc(super().get_prep_value(value))


class NFCTextField(models.TextField):
    def get_prep_value(self, value):
        return normalize_nfc(super().get_prep_value(value))


class NFCSlugField(models.SlugField):
    def get_prep_value(self, value):
        return normalize_nfc(super().get_prep_value(value))
