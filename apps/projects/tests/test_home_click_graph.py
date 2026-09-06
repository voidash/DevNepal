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
    # The authority is named once, in the state band, so the hero carries only the
    # office that publishes here.
    assert b"Office of the Prime Minister" in hero
    assert b"Government of Nepal" not in hero
    assert b"Digital Collaboration Initiative" not in hero
    assert b"Browse open issues" in hero
    assert b"Browse government projects" in hero
    assert b"Create an account" not in hero
    assert reverse("projects:issue_index").encode() in hero
    assert reverse("projects:government").encode() in hero
    assert reverse("projects:community").encode() not in response.content
    assert hero.count(b'class="btn') == 2


@pytest.mark.unit
def test_home_exposes_only_the_validated_catalog_and_issue_destinations(client):
    """A2.1/GOV-008: home discovery stays on the visitor issue-first spine."""
    response = client.get(reverse("projects:home"))
    content = response.content.decode()

    assert reverse("projects:issue_index") in content
    assert reverse("projects:government") in content
    assert reverse("recognition:public_badges") not in content
    assert reverse("recognition:public_policy") not in content


@pytest.mark.unit
def test_home_uses_one_four_step_journey_instead_of_a_filter_wall(client):
    """DSC-001/GOV-008: the first visit explains the GitHub flow without category overload."""
    response = client.get(reverse("projects:home"))
    content = response.content.decode()
    assert "From public project to GitHub contribution" in content
    assert content.count('class="dn-journey-step"') == 4
    assert 'class="dn-way-line"' not in content
    assert "Nine ways to contribute" not in content


@pytest.mark.unit
def test_home_hero_keeps_air_between_the_claim_the_actions_and_the_officer_line():
    """DSC-001: the home hero separates the lead, the two catalog actions, and the officer line."""
    css = (Path(settings.BASE_DIR) / "static/src/devnepal.css").read_text()

    assert ".dn-home-hero .hero__lead { max-width: 52ch; margin-top: var(--space-6); }" in css
    assert ".dn-home-hero .hero__actions { margin-top: var(--space-8); }" in css
    assert ".dn-home-hero .hero__ministry-link { display: block; margin: var(--space-8) 0 0;" in css


@pytest.mark.unit
def test_home_hero_does_not_show_the_decorative_illustration(client):
    """DSC-001: the hero leads with the claim; the board drawing stays parked."""
    response = client.get(reverse("projects:home"))
    css = (Path(settings.BASE_DIR) / "static/src/devnepal.css").read_text()
    hero_rule = css.split(".dn-home-hero {", 1)[1].split("}", 1)[0]

    assert response.status_code == 200
    assert b'class="dn-hero-illo"' not in response.content
    assert "grid-template-columns: minmax(0, 1fr)" in hero_rule


@pytest.mark.unit
def test_home_chapters_use_one_work_band_without_secondary_product_sections():
    """DSC-001: the compact home retains Madan's visual ground without extra chapters."""
    root = Path(settings.BASE_DIR)
    css = (root / "static/src/devnepal.css").read_text()
    home = (root / "apps/projects/templates/projects/home.html").read_text()
    mechanism = home.split('aria-labelledby="path-heading"', 1)[1].split(
        'aria-labelledby="opportunities-heading"', 1
    )[0]
    heading_rule = css.split(".dn-home-section-heading {", 1)[1].split("}", 1)[0]
    facts_rule = css.split(".dn-featured-card__facts {", 1)[1].split("}", 1)[0]
    assert '<section class="section dn-home" aria-labelledby="path-heading">' in home
    assert (
        '<section class="section dn-home dn-home--band" aria-labelledby="opportunities-heading">'
        in home
    )
    assert 'aria-labelledby="community-heading"' not in home
    assert 'aria-labelledby="people-heading"' not in home
    assert 'aria-labelledby="writing-heading"' not in home
    assert 'aria-labelledby="safeguards-heading"' not in home
    assert "dn-home--mute" not in home
    assert 'id="path-heading"' in mechanism
    assert "dn-journey" in mechanism
    assert ".section.dn-home--band { background: var(--color-paper); }" in css
    assert "border-bottom: 0;" in heading_rule
    assert "border-bottom: 1px" not in heading_rule
    assert "border-top: 0;" in facts_rule


@pytest.mark.unit
def test_home_tells_one_story_from_hero_to_the_ministry_cta(client):
    """DSC-001: home moves from purpose to process to government work to publishing."""
    response = client.get(reverse("projects:home"))
    content = response.content.decode()
    ordered = (
        'id="hero-heading"',
        'id="path-heading"',
        'id="opportunities-heading"',
        'id="ministry-cta-heading"',
    )
    positions = [content.index(marker) for marker in ordered]

    assert response.status_code == 200
    assert positions == sorted(positions)


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

    for route in ("projects:issue_index", "projects:government", "projects:about"):
        assert f'href="{reverse(route)}"' in primary
        assert f'href="{reverse(route)}"' in mobile

    assert f'<a class="dn-brand" href="{reverse("projects:home")}">' in content
    for route in (
        "projects:home",
        "projects:list",
        "projects:community",
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
    assert "From public project to GitHub contribution" in content
    assert "On DevNepal today" not in content
    assert "You pick an issue" in content
    assert 'id="path-heading"' in content
    assert "dn-way-chips" not in content
    assert "Choose your way in" not in content
    assert f'href="{reverse("projects:government")}"' in content
    assert f'href="{reverse("projects:community")}"' not in content
