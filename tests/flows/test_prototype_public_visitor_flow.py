"""Acceptance coverage for the source-of-truth public visitor journey."""

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.projects.models import Project


@pytest.mark.django_db
def test_public_visitor_can_follow_compact_home_catalog_detail_and_sign_in(client):
    """A1/A2/DSC-001: the compact anonymous path stays connected end to end."""
    call_command("seed_prototype_demo")

    home = client.get(reverse("projects:home"))
    assert home.status_code == 200
    home_content = home.content.decode()

    ordered_sections = (
        'id="hero-proof-heading"',
        'id="contribution-path-heading"',
        'id="path-heading"',
        'id="opportunities-heading"',
        'id="community-heading"',
        'id="safeguards-heading"',
        'id="ministry-cta-heading"',
    )
    positions = [home_content.index(section) for section in ordered_sections]
    assert positions == sorted(positions)

    government = client.get(reverse("projects:government"))
    assert government.status_code == 200
    assert "Civic Help Directory" in government.content.decode()

    project = Project.objects.get(slug="sewa-portal-accessibility-remediation")
    detail_url = reverse("projects:detail", kwargs={"slug": project.slug})
    detail = client.get(detail_url)
    assert detail.status_code == 200
    detail_content = detail.content.decode()
    assert "voidash/civic-help-directory" in detail_content
    assert "Open tasks" in detail_content
    assert "Add Nepali eligibility text for scholarship programs" in detail_content
    assert "https://github.com/voidash/civic-help-directory/issues/7" in detail_content
    assert "Sign in to apply" not in detail_content


@pytest.mark.django_db
def test_home_calls_to_action_link_to_real_public_destinations(client):
    """A1/A3/DSC-001: compact home calls-to-action are routes, not decorative controls."""
    call_command("seed_prototype_demo")

    response = client.get(reverse("projects:home"))
    content = response.content.decode()

    for route_name in (
        "projects:government",
        "projects:community",
        "accounts:member_directory",
        "blogs:list",
        "recognition:leaderboard",
        "recognition:public_badges",
        "recognition:public_policy",
        "projects:about",
        "projects:code_of_conduct",
        "projects:privacy_policy",
        "projects:security_policy",
        "accounts:login",
    ):
        assert reverse(route_name) in content

    for route_name in (
        "projects:code_of_conduct",
        "projects:privacy_policy",
        "projects:security_policy",
    ):
        destination = client.get(reverse(route_name))
        assert destination.status_code == 200
        assert "Public policy" in destination.content.decode()
