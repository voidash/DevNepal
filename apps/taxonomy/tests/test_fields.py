import unicodedata

import pytest

from apps.taxonomy.fields import normalize_nfc
from apps.taxonomy.tests.factories import SkillFactory

pytestmark = pytest.mark.unit


def test_normalize_nfc_composes_nfd_and_strips():
    """DSC-003: helper composes NFD Devanagari input to NFC and strips edge whitespace."""
    nfd = unicodedata.normalize("NFD", "प्रविधि समीक्षा")
    assert normalize_nfc(f"  {nfd} ") == "प्रविधि समीक्षा"


def test_normalize_nfc_passthrough_non_string():
    """DSC-003: non-string values (e.g. None from empty fields) pass through unchanged."""
    assert normalize_nfc(None) is None
    assert normalize_nfc(42) == 42


@pytest.mark.django_db
def test_nfc_char_and_slug_fields_normalize_on_save():
    """DSC-003: NFCCharField and NFCSlugField persist NFC-composed, trimmed values."""
    nfd = unicodedata.normalize("NFD", "प्रविधि")
    skill = SkillFactory(name=f"  {nfd} ", slug=nfd)
    refreshed = type(skill).objects.get(pk=skill.pk)
    assert refreshed.name == "प्रविधि"
    assert refreshed.slug == unicodedata.normalize("NFC", nfd)


@pytest.mark.django_db
def test_nfc_text_field_normalizes_on_save():
    """DSC-003: NFCTextField persists NFC-composed, trimmed long text."""
    nfd = unicodedata.normalize("NFD", "यो एक लामो विवरण हो")
    skill = SkillFactory(description=f"  {nfd}  ")
    refreshed = type(skill).objects.get(pk=skill.pk)
    assert refreshed.description == unicodedata.normalize("NFC", "यो एक लामो विवरण हो")


@pytest.mark.django_db
def test_nfc_fields_keep_none_and_empty_saveable():
    """DSC-003: blank NFC fields stay blank instead of crashing on non-str input."""
    skill = SkillFactory(description="")
    refreshed = type(skill).objects.get(pk=skill.pk)
    assert refreshed.description == ""
