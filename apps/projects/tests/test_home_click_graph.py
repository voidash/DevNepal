import pytest
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
def test_home_uses_the_real_github_post_boundary_only_when_configured(client):
    """AUTH-002/GIT-002: configured GitHub hero action starts the OAuth boundary."""
    response = client.get(reverse("projects:home"))

    assert response.status_code == 200
    assert f'action="{reverse("accounts:github_connect")}"'.encode() in response.content
    assert b"Join with GitHub" in response.content


@pytest.mark.unit
@override_settings(GITHUB_CLIENT_ID="", GITHUB_CLIENT_SECRET="", GITHUB_OAUTH_ENABLED=False)
def test_home_labels_the_disabled_github_path_as_account_creation(client):
    """AUTH-001: the anonymous hero never promises GitHub sign-in when OAuth is unavailable."""
    response = client.get(reverse("projects:home"))

    assert response.status_code == 200
    assert b"Create an account" in response.content
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
    assert b"Browse government projects" in hero
    assert b"Create an account" in hero
    assert b"Community projects" not in hero
    assert b"Ministry officer?" not in hero
    assert reverse("projects:community").encode() not in hero
    assert reverse("projects:ministry_onboarding").encode() not in hero
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
    assert f'href="{reverse("accounts:signup")}"'.encode() in response.content
    assert "Create an account" in content


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
    assert "DevNepal — platform at a glance" in content
    assert "People — verified impact and the people behind it" in content
    assert "Writing from the community" in content
    assert "Choose your way in" not in content
    assert f'href="{reverse("projects:government")}"' in content
    assert f'href="{reverse("projects:community")}"' in content
