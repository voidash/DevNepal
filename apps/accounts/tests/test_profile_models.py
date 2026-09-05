import unicodedata

import pytest
from django.db import IntegrityError
from django.db.models import ProtectedError

from apps.accounts.enums import Availability, Province
from apps.accounts.models import MemberEducation, MemberLink, MemberProfile, MemberSkill
from apps.accounts.services import export_profile_data, public_profile_payload
from apps.accounts.tests.factories import (
    MemberEducationFactory,
    MemberLinkFactory,
    MemberProfileFactory,
    MemberSkillFactory,
    UserFactory,
)
from apps.taxonomy.enums import ContentLanguage
from apps.taxonomy.tests.factories import SkillFactory

pytestmark = pytest.mark.django_db


@pytest.mark.unit
def test_mem001_u1_duplicate_username_rejected():
    """MEM-001-U1: duplicate public username is rejected across the platform."""
    UserFactory(username="unique_handle")
    with pytest.raises(IntegrityError):
        UserFactory(username="unique_handle")


@pytest.mark.unit
def test_mem001_u2_internal_identifier_immutable():
    """MEM-001-U2: internal identifier is immutable; username change preserves it."""
    user = UserFactory(username="before")
    original_pk = user.pk
    user.username = "after"
    user.save(update_fields=["username"])
    user.refresh_from_db()
    assert user.pk == original_pk
    assert user.username == "after"


@pytest.mark.unit
def test_mem002_u1_profile_fields_round_trip():
    """MEM-002-U1: all specified profile fields (name ... contribution preferences) round-trip."""
    user = UserFactory(first_name="Sita")
    profile = MemberProfileFactory(
        user=user,
        headline="Civic-tech engineer",
        bio="Builds public services",
        location="Kathmandu",
        province=Province.BAGMATI,
        preferred_language=ContentLanguage.NEPALI,
        experience_band="senior",
        availability=Availability.LIMITED,
        interests="open data, maps",
        contribution_preferences="documentation, QA",
        field_visibility={"location": "public"},
        directory_discoverable=True,
        leaderboard_opt_out=True,
    )
    stored = MemberProfile.objects.get(pk=profile.pk)
    assert stored.user == user
    assert user.first_name == "Sita"
    assert stored.headline == "Civic-tech engineer"
    assert stored.bio == "Builds public services"
    assert stored.location == "Kathmandu"
    assert stored.province == Province.BAGMATI
    assert stored.preferred_language == ContentLanguage.NEPALI
    assert stored.experience_band == "senior"
    assert stored.availability == Availability.LIMITED
    assert stored.interests == "open data, maps"
    assert stored.contribution_preferences == "documentation, QA"
    assert stored.field_visibility == {"location": "public"}
    assert stored.directory_discoverable is True
    assert stored.leaderboard_opt_out is True
    assert not stored.avatar
    assert stored.created_at is not None
    assert stored.updated_at is not None


@pytest.mark.integration
def test_mem002_i1_devanagari_stored_nfc_normalized():
    """MEM-002-I1, DSC-003: Devanagari profile edits are stored NFC-normalized on save."""
    nfd_text = "\u0928\u093c\u0947\u092a\u093e\u0932\u0940" + "\u0930\u093c"
    nfc_text = unicodedata.normalize("NFC", nfd_text)
    assert nfd_text != nfc_text
    profile = MemberProfileFactory(
        headline=nfd_text,
        bio=nfd_text,
        location=nfd_text,
        interests=nfd_text,
        contribution_preferences=nfd_text,
    )
    stored = MemberProfile.objects.get(pk=profile.pk)
    assert stored.headline == nfc_text
    assert stored.bio == nfc_text
    assert stored.location == nfc_text
    assert stored.interests == nfc_text
    assert stored.contribution_preferences == nfc_text


@pytest.mark.unit
def test_mem005_u1_portfolio_sections_use_separate_relations():
    """MEM-005-U1: profile portfolio data is queryable through separate per-section relations."""
    user = UserFactory()
    profile = MemberProfileFactory(user=user)
    MemberLinkFactory(user=user, url="https://github.com/sita", is_public=True)
    MemberLinkFactory(user=user, url="https://blog.example.com/sita", is_public=False)
    MemberEducationFactory(user=user, institution="Tribhuvan University")

    assert user.profile == profile
    assert user.links.count() == 2
    assert user.education.count() == 1
    assert MemberLink.objects.filter(user=user).count() == 2


@pytest.mark.unit
def test_br004_u1_self_declared_data_never_published_or_verified():
    """BR-004-U1: self-declared profile data is never serialized as government-verified; MEM-003,
    §12.2: education records are never published even when visibility is configured public."""
    user = UserFactory(email="sita@example.com")
    profile = MemberProfileFactory(
        user=user,
        field_visibility={"education": "public", "location": "public"},
    )
    MemberEducationFactory(user=user, institution="Tribhuvan University")
    payload = public_profile_payload(profile)
    assert "education" not in payload
    assert "sita@example.com" not in str(payload)
    assert "verified" not in str(payload).lower()


@pytest.mark.unit
def test_mem002_u1_member_skills_reference_taxonomy_terms():
    """MEM-002-U1, MEM-004: member skills link to taxonomy terms; terms are PROTECTed (BR-012)."""
    user = UserFactory()
    skill = SkillFactory(name="MapLibre")
    MemberSkillFactory(user=user, skill=skill, self_rating="advanced")
    stored = MemberSkill.objects.get(user=user, skill=skill)
    assert stored.self_rating == "advanced"
    assert user.skills.count() == 1
    with pytest.raises(ProtectedError):
        skill.delete()


@pytest.mark.unit
def test_mem002_u1_duplicate_member_skill_rejected():
    """MEM-002-U1: at most one row per user per taxonomy skill."""
    user = UserFactory()
    skill = SkillFactory(name="Nepali NLP")
    MemberSkillFactory(user=user, skill=skill)
    with pytest.raises(IntegrityError):
        MemberSkillFactory(user=user, skill=skill)


@pytest.mark.unit
def test_br004_u1_self_rating_never_serialized_as_verified():
    """BR-004-U1: self-declared skill ratings serialize as self-declared, never as verified."""
    user = UserFactory()
    profile = MemberProfileFactory(user=user, field_visibility={"skills": "public"})
    MemberSkillFactory(user=user, skill=SkillFactory(name="MapLibre"), self_rating="expert")
    payload = public_profile_payload(profile)
    assert payload["skills"] == [{"name": "MapLibre", "self_rating": "expert"}]
    assert "verified" not in str(payload).lower()
    exported = export_profile_data(user)
    assert exported["skills"] == [{"name": "MapLibre", "self_rating": "expert"}]


@pytest.mark.unit
def test_dsc003_link_and_education_text_nfc_normalized():
    """DSC-003: NFC normalization applies to link labels and education text on save."""
    nfd_text = "\u0928\u093c\u0947\u092a\u093e\u0932\u0940"
    nfc_text = unicodedata.normalize("NFC", nfd_text)
    assert nfd_text != nfc_text
    link = MemberLinkFactory(label=nfd_text)
    education = MemberEducationFactory(credential=nfd_text, field_of_study=nfd_text)
    stored_link = MemberLink.objects.get(pk=link.pk)
    stored_education = MemberEducation.objects.get(pk=education.pk)
    assert stored_link.label == nfc_text
    assert stored_education.credential == nfc_text
    assert stored_education.field_of_study == nfc_text
