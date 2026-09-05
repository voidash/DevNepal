import unicodedata

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import translation

from apps.accounts.enums import Visibility
from apps.accounts.tests.factories import MemberProfileFactory, MemberSkillFactory, UserFactory
from apps.taxonomy.tests.factories import SkillFactory

pytestmark = pytest.mark.django_db


@pytest.mark.integration
def test_mem003_i2_member_directory_exposes_only_opted_in_public_profiles(client):
    """MEM-003/DSC-003/NFR-A11Y-01: public directory search is NFC-safe and never exposes
    private skills, inactive members, or contact data."""
    skill = SkillFactory(name="प्रविधि समीक्षा", slug="technology-review")
    public_user = UserFactory(username="public-member", email="public@example.com")
    MemberProfileFactory(
        user=public_user,
        headline="Public-service reviewer",
        interests="Digital service delivery",
        directory_discoverable=True,
        field_visibility={"skills": Visibility.PUBLIC},
    )
    MemberSkillFactory(user=public_user, skill=skill)

    private_skill_user = UserFactory(username="private-skill-member", email="private@example.com")
    MemberProfileFactory(
        user=private_skill_user,
        headline="Private skill holder",
        interests="Private research",
        directory_discoverable=True,
        field_visibility={"skills": Visibility.PRIVATE},
    )
    MemberSkillFactory(user=private_skill_user, skill=skill)

    opted_out_user = UserFactory(username="opted-out-member", email="opted-out@example.com")
    MemberProfileFactory(
        user=opted_out_user,
        headline="Hidden member",
        interests="Digital service delivery",
        directory_discoverable=False,
        field_visibility={"skills": Visibility.PUBLIC},
    )
    MemberSkillFactory(user=opted_out_user, skill=skill)

    inactive_user = UserFactory(
        username="inactive-member", email="inactive@example.com", is_active=False
    )
    MemberProfileFactory(
        user=inactive_user,
        headline="Inactive member",
        interests="Digital service delivery",
        directory_discoverable=True,
        field_visibility={"skills": Visibility.PUBLIC},
    )
    MemberSkillFactory(user=inactive_user, skill=skill)

    response = client.get(
        reverse("accounts:member_directory"),
        {"q": unicodedata.normalize("NFD", skill.name), "skill": skill.slug},
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert response.context["query"] == skill.name
    assert response.context["members"].paginator.count == 1
    assert public_user.username in content
    assert skill.name in content
    assert private_skill_user.username not in content
    assert opted_out_user.username not in content
    assert inactive_user.username not in content
    assert b"private@example.com" not in response.content
    assert 'role="search"' in content
    assert 'for="member-search"' in content


@pytest.mark.integration
def test_mem003_i2_member_directory_empty_state_and_navigation_are_actionable(client):
    """MEM-003/NFR-A11Y-01/NFR-I18N-01: the empty directory explains the opt-in boundary,
    remains reachable from public navigation, and has a Nepali route."""
    response = client.get(reverse("accounts:member_directory"))
    home = client.get(reverse("projects:home"))
    with translation.override("ne"):
        nepali = client.get(reverse("accounts:member_directory"))

    assert response.status_code == 200
    assert "No members match these filters." in response.content.decode()
    assert reverse("accounts:member_directory").encode() in home.content
    assert nepali.status_code == 200
    assert '<html lang="ne"' in nepali.content.decode()
    assert "सदस्यहरू" in nepali.content.decode()


@pytest.mark.integration
def test_mem003_i2_member_directory_query_count_stays_bounded_as_profiles_grow(client):
    """MEM-003: member-directory rendering prefetches public skills and avoids an N+1 query
    for each opted-in profile."""
    skill = SkillFactory(name="Open data", slug="open-data")
    for index in range(26):
        user = UserFactory(username=f"directory-member-{index}")
        MemberProfileFactory(
            user=user,
            headline=f"Member {index}",
            directory_discoverable=True,
            field_visibility={"skills": Visibility.PUBLIC},
        )
        MemberSkillFactory(user=user, skill=skill)

    url = reverse("accounts:member_directory")
    warm = client.get(url)
    assert warm.status_code == 200
    with CaptureQueriesContext(connection) as queries:
        response = client.get(url)

    assert response.status_code == 200
    assert len(queries) <= 6
    assert 'aria-label="Member pages"' in response.content.decode()
