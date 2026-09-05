import pytest
from django.urls import reverse

from apps.accounts.tests.factories import MemberSkillFactory
from apps.projects.enums import ProjectStatus
from apps.projects.tests.factories import ProjectFactory, UserFactory
from apps.taxonomy.models import Skill

pytestmark = pytest.mark.django_db


@pytest.mark.integration
def test_b201_member_catalog_explains_a_recommendation_without_exposing_it_publicly(client):
    """B2.1/DSC-010: catalog recommendations are member-scoped and explain their source."""
    member = UserFactory()
    django = Skill.objects.get(name="Django")
    MemberSkillFactory(user=member, skill=django)
    project = ProjectFactory(
        title_en="B2 accessibility work",
        status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
    )
    project.skills.add(django)

    catalog_url = reverse("projects:government")
    client.force_login(member)
    member_response = client.get(catalog_url)
    client.logout()
    public_response = client.get(catalog_url)

    assert member_response.status_code == 200
    assert "Recommended for you" in member_response.content.decode()
    assert "Matches your Django skill" in member_response.content.decode()
    assert "Recommended for you" not in public_response.content.decode()
