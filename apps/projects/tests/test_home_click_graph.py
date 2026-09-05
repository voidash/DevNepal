from pathlib import Path

import pytest
from django.conf import settings
from django.test import override_settings
from django.urls import reverse

pytestmark = pytest.mark.django_db


@pytest.mark.unit
def test_home_empty_opportunities_keeps_a_government_catalog_exit(client):
    """A2.1/DSC-001: the empty home state still lets an anonymous visitor browse government work."""
    response = client.get(reverse("projects:home"))

    assert response.status_code == 200
    assert reverse("projects:government").encode() in response.content


@pytest.mark.unit
@override_settings(
    GITHUB_CLIENT_ID="client-id",
    GITHUB_CLIENT_SECRET="client-secret",
    GITHUB_OAUTH_ENABLED=True,
)
def test_home_offers_no_account_route_even_when_github_oauth_is_configured(client):
    """AUTH-001/AUTH-002: contributing needs no account, so home never starts OAuth."""
    response = client.get(reverse("projects:home"))

    assert response.status_code == 200
    assert f'action="{reverse("accounts:github_connect")}"'.encode() not in response.content
    assert b"Join with GitHub" not in response.content
    assert b"no DevNepal account is needed" in response.content


@pytest.mark.unit
@override_settings(GITHUB_CLIENT_ID="", GITHUB_CLIENT_SECRET="", GITHUB_OAUTH_ENABLED=False)
def test_home_sends_officers_to_sign_in_and_everyone_else_to_the_work(client):
    """AUTH-001: the anonymous hero routes officers to sign-in and never promises OAuth."""
    response = client.get(reverse("projects:home"))

    assert response.status_code == 200
    assert b"Ministry sign-in" in response.content
    assert b"Join with GitHub" not in response.content


@pytest.mark.unit
@override_settings(GITHUB_CLIENT_ID="", GITHUB_CLIENT_SECRET="", GITHUB_OAUTH_ENABLED=False)
def test_home_hero_offers_exactly_two_visitor_actions(client):
    """DSC-001/GOV-007: the hero keeps one official catalog action and one account action."""
    response = client.get(reverse("projects:home"))
    hero = response.content.split(b'<section class="hero"', 1)[1].split(b"</section>", 1)[0]

    assert response.status_code == 200
    assert b"Government of Nepal" in hero
    assert b"Digital Collaboration Initiative" not in hero
    assert b"Browse open issues" in hero
    assert b"Browse government projects" in hero
    assert b"Create an account" not in hero
    assert reverse("projects:issue_index").encode() in hero
    assert reverse("projects:government").encode() in hero
    assert reverse("projects:community").encode() in response.content
    assert hero.count(b'class="btn') == 2


@pytest.mark.unit
def test_home_exposes_real_catalog_filters_and_public_recognition_destinations(client):
    """A2.1/A3.6/A3.7/GOV-008: home discovery links retain category and recognition destinations."""
    response = client.get(reverse("projects:home"))
    content = response.content.decode()

    assert f"{reverse('projects:government')}?contribution_type=engineering" in content
    assert f"{reverse('projects:government')}?contribution_type=uiux" in content
    assert reverse("recognition:public_badges") in content
    assert reverse("recognition:public_policy") in content


@pytest.mark.unit
def test_home_names_nine_contribution_types_as_a_legend_not_a_filter_wall(client):
    """DSC-001/GOV-008: nine types are named as a legend; filters stay on the door cards."""
    response = client.get(reverse("projects:home"))
    content = response.content.decode()
    way_line = content.split('class="dn-way-line"', 1)[1].split("</ul>", 1)[0]

    assert "<a " not in way_line
    for label in (
        "Engineering",
        "UI/UX",
        "QA",
        "Security",
        "Data",
        "Documentation",
        "Localization",
        "Research",
        "Community support",
    ):
        assert label in way_line
    assert f"{reverse('projects:government')}?contribution_type=engineering" in content
    assert f"{reverse('projects:government')}?contribution_type=uiux" in content
    assert "dn-way-chips" not in content


@pytest.mark.unit
def test_home_hero_keeps_air_between_the_claim_the_actions_and_the_officer_line():
    """DSC-001: the home hero separates the lead, the two catalog actions, and the officer line."""
    css = (Path(settings.BASE_DIR) / "static/src/devnepal.css").read_text()

    assert ".dn-home-hero .hero__lead { max-width: 52ch; margin-top: var(--space-6); }" in css
    assert ".dn-home-hero .hero__actions { margin-top: var(--space-8); }" in css
    assert ".dn-home-hero .hero__ministry-link { display: block; margin: var(--space-8) 0 0;" in css


@pytest.mark.unit
def test_public_ministry_onboarding_is_an_explainer_not_an_application(client):
    """C1.1/C1.3/GOV-001: prospective officers receive an onboarding explanation."""
    response = client.get(reverse("projects:ministry_onboarding"))
    main = response.content.split(b"<main", 1)[1].split(b"</main>", 1)[0]

    assert response.status_code == 200
    assert b"Become a ministry publisher" in response.content
    assert b"<form" not in main


@pytest.mark.unit
def test_anonymous_mobile_menu_contains_account_entry_points(client):
    """AUTH-001: responsive anonymous navigation keeps sign-in and account creation reachable."""
    response = client.get(reverse("projects:home"))
    content = response.content.decode()

    assert f'href="{reverse("accounts:login")}"'.encode() in response.content
    assert "Ministry sign-in" in content


@pytest.mark.unit
def test_public_shell_prioritizes_open_work_without_duplicate_home_navigation(client):
    """DSC-001/A2.1: the brand is Home and the visitor menu prioritizes discovery."""
    response = client.get(reverse("projects:home"))
    content = response.content.decode()
    primary = content.split('<nav class="dn-primary-nav"', 1)[1].split("</nav>", 1)[0]
    mobile = content.split('<details class="mobile-nav">', 1)[1].split("</details>", 1)[0]

    for route in ("projects:government", "projects:community", "projects:about"):
        assert f'href="{reverse(route)}"' in primary
        assert f'href="{reverse(route)}"' in mobile

    assert f'<a class="dn-brand" href="{reverse("projects:home")}">' in content
    for route in (
        "projects:home",
        "projects:list",
        "accounts:member_directory",
        "blogs:list",
        "recognition:leaderboard",
    ):
        assert f'href="{reverse(route)}"' not in primary
        assert f'href="{reverse(route)}"' not in mobile


@pytest.mark.unit
def test_home_keeps_only_first_visit_decisions_and_real_project_exits(client):
    """DSC-001/GOV-011: home leads with trusted open work rather than secondary dashboards."""
    response = client.get(reverse("projects:home"))
    content = response.content.decode()

    assert "Featured government projects" in content
    assert "Code is one of nine ways in" in content
    assert "What is published here" in content
    assert "From listing to public record" in content
    assert 'id="path-heading"' in content
    assert "dn-way-chips" not in content
    assert "Choose your way in" not in content
    assert f'href="{reverse("projects:government")}"' in content
    assert f'href="{reverse("projects:community")}"' in content
