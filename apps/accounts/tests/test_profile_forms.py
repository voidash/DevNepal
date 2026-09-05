import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.enums import Visibility
from apps.accounts.forms import MemberProfileForm
from apps.accounts.services import VISIBILITY_CONTROLLED_FIELDS
from apps.accounts.tests.factories import MemberProfileFactory, MemberSkillFactory
from apps.taxonomy.tests.factories import SkillFactory


@pytest.mark.unit
@pytest.mark.django_db
def test_mem002_u1_profile_form_covers_editable_fields_and_visibility_choices():
    """MEM-002/MEM-003: profile form exposes every editable field and valid visibility choices."""
    profile = MemberProfileFactory(field_visibility={"location": Visibility.PUBLIC})

    form = MemberProfileForm(instance=profile)

    assert set(form.fields) == {
        "headline",
        "bio",
        "location",
        "province",
        "preferred_language",
        "experience_band",
        "availability",
        "interests",
        "contribution_preferences",
        "avatar",
        "skills",
        "directory_discoverable",
        "leaderboard_opt_out",
        *(f"visibility_{field}" for field in VISIBILITY_CONTROLLED_FIELDS),
    }
    assert form.fields["visibility_location"].initial == Visibility.PUBLIC
    assert set(form.fields["visibility_location"].choices) == set(Visibility.choices)


@pytest.mark.unit
@pytest.mark.django_db
def test_mem002_u1_profile_form_rejects_invalid_model_and_visibility_choices():
    """MEM-002/MEM-003: profile form returns field-level errors for invalid submitted choices."""
    form = MemberProfileForm(
        data={
            "province": "not-a-province",
            "preferred_language": "not-a-language",
            "availability": "not-available",
            "visibility_location": "not-a-visibility",
        },
        instance=MemberProfileFactory(),
    )

    assert not form.is_valid()
    assert set(form.errors) == {
        "province",
        "preferred_language",
        "availability",
        "visibility_location",
    }


@pytest.mark.unit
@pytest.mark.django_db
def test_mem002_u1_avatar_accepts_only_bounded_real_image_signatures():
    """MEM-002/SEC-007: photograph uploads reject disguised files."""
    profile = MemberProfileFactory()
    valid = SimpleUploadedFile(
        "portrait.png", b"\x89PNG\r\n\x1a\n" + b"x", content_type="image/png"
    )
    valid_form = MemberProfileForm(data={}, files={"avatar": valid}, instance=profile)
    assert valid_form.is_valid()

    disguised = SimpleUploadedFile("portrait.png", b"MZ\x90\x00", content_type="image/png")
    invalid_form = MemberProfileForm(data={}, files={"avatar": disguised}, instance=profile)
    assert not invalid_form.is_valid()
    assert "avatar" in invalid_form.errors


@pytest.mark.unit
@pytest.mark.django_db
def test_mem002_u1_profile_form_rejects_overlong_headline():
    """MEM-002: profile form returns an actionable field error for invalid profile text."""
    form = MemberProfileForm(
        data={"headline": "x" * 201},
        instance=MemberProfileFactory(),
    )

    assert not form.is_valid()
    assert "headline" in form.errors


@pytest.mark.unit
@pytest.mark.django_db
def test_mem004_u1_skills_selector_offers_only_taxonomy_terms():
    """MEM-004-U1: the skill selector loads options from the admin-managed taxonomy."""
    profile = MemberProfileFactory()
    SkillFactory(name="Civic Django")
    SkillFactory(name="Civic Retired Skill", is_active=False)

    form = MemberProfileForm(instance=profile)

    offered = set(form.fields["skills"].queryset.values_list("name", flat=True))
    assert "Civic Django" in offered
    assert "Civic Retired Skill" not in offered
    assert form.fields["skills"].required is False


@pytest.mark.unit
@pytest.mark.django_db
def test_mem004_u1_skills_selection_rejects_terms_missing_from_taxonomy():
    """MEM-004-U1: a term outside the taxonomy is rejected into an error, not stored."""
    profile = MemberProfileFactory()
    known = SkillFactory(name="Civic Python")
    retired = SkillFactory(name="Civic Perl", is_active=False)

    form = MemberProfileForm(
        data={"skills": [str(known.pk), str(retired.pk), "999999"]},
        instance=profile,
    )

    assert not form.is_valid()
    assert set(form.errors) == {"skills"}
    assert not profile.user.skills.exists()


@pytest.mark.integration
@pytest.mark.django_db
def test_mem004_i1_skills_add_and_remove_on_save():
    """MEM-004-I1: saving the editor reconciles MemberSkill rows with the selection."""
    profile = MemberProfileFactory()
    keep = SkillFactory(name="Civic Rust")
    SkillFactory(name="Civic Go")
    dropped = SkillFactory(name="Civic Perl")
    MemberSkillFactory(user=profile.user, skill=dropped)

    form = MemberProfileForm(data={"skills": [str(keep.pk)]}, instance=profile)

    assert form.is_valid(), form.errors
    form.save()
    assert set(profile.user.skills.values_list("skill__name", flat=True)) == {"Civic Rust"}
    assert not profile.user.skills.filter(skill=dropped).exists()
