import pytest

from apps.accounts.enums import Province, Visibility
from apps.accounts.services import (
    preview_public_profile,
    profile_completeness,
    public_profile_payload,
)
from apps.accounts.tests.factories import (
    MemberEducationFactory,
    MemberLinkFactory,
    MemberProfileFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db


@pytest.mark.unit
def test_mem003_u1_public_payload_omits_private_defaults():
    """MEM-003-U1: public serialization omits email, provider, and private contact info."""
    user = UserFactory(email="sita@example.com")
    profile = MemberProfileFactory(
        user=user,
        location="Kathmandu",
        province=Province.BAGMATI,
        field_visibility={},
    )
    payload = public_profile_payload(profile)
    assert payload["username"] == user.username
    assert "email" not in payload
    assert "sita@example.com" not in str(payload)
    assert "provider" not in str(payload).lower()
    assert "location" not in payload
    assert "province" not in payload
    assert payload["links"] == []
    assert payload["skills"] == []
    assert profile.directory_discoverable is False


@pytest.mark.integration
def test_mem003_i1_field_visibility_toggles_public_view():
    """MEM-003-I1: toggling field_visibility changes what the public profile view exposes."""
    user = UserFactory()
    profile = MemberProfileFactory(
        user=user,
        location="Kathmandu",
        province=Province.BAGMATI,
        field_visibility={"location": Visibility.PUBLIC, "province": Visibility.PRIVATE},
    )
    payload = public_profile_payload(profile)
    assert payload["location"] == "Kathmandu"
    assert "province" not in payload

    profile.field_visibility = {
        "location": Visibility.PRIVATE,
        "province": Visibility.PUBLIC,
    }
    profile.save()
    payload = public_profile_payload(profile)
    assert "location" not in payload
    assert payload["province"] == Province.BAGMATI


@pytest.mark.unit
def test_mem003_u1_links_public_only_when_marked_public():
    """MEM-003-U1: member links stay non-public until is_public and section visibility allow it."""
    user = UserFactory()
    profile = MemberProfileFactory(user=user, field_visibility={})
    MemberLinkFactory(user=user, url="https://github.com/sita", is_public=True)
    MemberLinkFactory(user=user, url="https://blog.example.com/sita", is_public=False)
    assert public_profile_payload(profile)["links"] == []

    profile.field_visibility = {"links": Visibility.PUBLIC}
    profile.save()
    payload = public_profile_payload(profile)
    assert [link["url"] for link in payload["links"]] == ["https://github.com/sita"]


@pytest.mark.integration
def test_mem008_i1_preview_shows_pending_changes_without_publishing():
    """MEM-008-I1: preview renders the post-change public profile without publishing it."""
    user = UserFactory()
    profile = MemberProfileFactory(user=user, headline="Published headline")
    profile.headline = "Draft headline"
    profile.location = "Lalitpur"
    profile.field_visibility = {"location": Visibility.PUBLIC}

    payload = preview_public_profile(profile)
    assert payload["headline"] == "Draft headline"
    assert payload["location"] == "Lalitpur"

    stored = MemberProfileFactory._meta.model.objects.get(pk=profile.pk)
    assert stored.headline == "Published headline"
    assert stored.field_visibility == {}


@pytest.mark.unit
def test_mem009_u1_completeness_guidance_never_requires_sensitive_fields():
    """MEM-009-U1: completeness guidance computed; sensitive optional fields never required."""
    user = UserFactory()
    profile = MemberProfileFactory(user=user)

    empty = profile_completeness(profile)
    assert empty["percent"] == 0
    assert empty["items"]
    sensitive = [item for item in empty["items"] if item["sensitive"]]
    assert sensitive
    assert all(item["required"] is False for item in empty["items"])

    profile.headline = "Civic-tech engineer"
    profile.bio = "Builds public services"
    profile.interests = "open data"
    profile.save()
    MemberLinkFactory(user=user, url="https://github.com/sita", is_public=True)
    MemberEducationFactory(user=user, institution="Tribhuvan University")

    filled = profile_completeness(MemberProfileFactory._meta.model.objects.get(pk=profile.pk))
    assert 0 < filled["percent"] < 100
    assert sum(item["filled"] for item in filled["items"]) > 3
