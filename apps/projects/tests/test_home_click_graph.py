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
@override_settings(GITHUB_CLIENT_ID="client-id", GITHUB_CLIENT_SECRET="client-secret")
def test_home_never_uses_member_oauth_as_the_public_contribution_boundary(client):
    """GIT-002: public contribution starts from a project issue, not member OAuth."""
    response = client.get(reverse("projects:home"))

    assert response.status_code == 200
    assert reverse("accounts:github_connect").encode() not in response.content
    assert b"Join with GitHub" not in response.content
    assert b"Browse government projects" in response.content


@pytest.mark.unit
@override_settings(GITHUB_CLIENT_ID="", GITHUB_CLIENT_SECRET="", GITHUB_OAUTH_ENABLED=False)
def test_home_does_not_offer_a_contributor_account_when_oauth_is_unavailable(client):
    """AUTH-001: visitors contribute on GitHub without creating a DevNepal account."""
    response = client.get(reverse("projects:home"))

    assert response.status_code == 200
    assert b"Create an account" not in response.content
    assert b"Join with GitHub" not in response.content


@pytest.mark.unit
def test_home_exposes_only_catalog_and_contribution_guidance_destinations(client):
    """A2.1/GOV-008: first-visit choices stay inside the validated visitor spine."""
    response = client.get(reverse("projects:home"))
    content = response.content.decode()

    assert reverse("projects:government") in content
    assert reverse("projects:about") in content
    assert reverse("recognition:public_badges") not in content
    assert reverse("recognition:public_policy") not in content


@pytest.mark.unit
def test_public_ministry_onboarding_is_an_explainer_not_an_application(client):
    """C1.1/C1.3/GOV-001: prospective officers receive an onboarding explanation."""
    response = client.get(reverse("projects:ministry_onboarding"))
    main = response.content.split(b"<main", 1)[1].split(b"</main>", 1)[0]

    assert response.status_code == 200
    assert b"Become a ministry publisher" in response.content
    assert b"<form" not in main


@pytest.mark.unit
def test_anonymous_mobile_menu_contains_only_the_ministry_account_entry(client):
    """AUTH-001: responsive navigation distinguishes ministry access from contributors."""
    response = client.get(reverse("projects:home"))
    content = response.content.decode()

    assert f'href="{reverse("accounts:login")}"'.encode() in response.content
    assert f'href="{reverse("accounts:signup")}"'.encode() not in response.content
    assert "Ministry sign in" in content
    assert "Create an account" not in content


@pytest.mark.unit
def test_public_shell_prioritizes_open_work_without_duplicate_home_navigation(client):
    """DSC-001/A2.1: the brand is Home and the visitor menu prioritizes discovery."""
    response = client.get(reverse("projects:home"))
    content = response.content.decode()
    primary = content.split('<nav class="dn-primary-nav"', 1)[1].split("</nav>", 1)[0]
    mobile = content.split('<details class="mobile-nav">', 1)[1].split("</details>", 1)[0]

    for route in ("projects:government", "projects:about"):
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
    assert "DevNepal — platform at a glance" not in content
    assert "People — verified impact and the people behind it" not in content
    assert "Writing from the community" not in content
    assert "Choose your way in" not in content
    assert f'href="{reverse("projects:government")}"' in content
    assert f'href="{reverse("projects:community")}"' not in content
    assert "Create an account" not in content
    assert "Join with GitHub" not in content
