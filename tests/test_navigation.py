import pytest
from django.urls import reverse
from django.utils.translation import override


@pytest.mark.django_db
@pytest.mark.unit
def test_shared_navigation_uses_resolvable_localized_routes(client):
    """DSC-001/A8: shared navigation never sends visitors to an unprefixed or missing route."""
    response = client.get(reverse("projects:home"))

    assert response.status_code == 200
    for destination in (
        reverse("projects:home"),
        reverse("projects:government"),
        reverse("projects:about"),
        reverse("accounts:login"),
    ):
        assert f'href="{destination}"'.encode() in response.content


@pytest.mark.django_db
@pytest.mark.unit
def test_primary_navigation_exposes_only_the_validated_visitor_choices(client):
    """DSC-001/NFR-A11Y-01: the public shell stays on the GitHub-first spine."""
    response = client.get(reverse("projects:home"))
    primary_start = response.content.index(b'<nav class="dn-primary-nav"')
    primary_end = response.content.index(b"</nav>", primary_start)
    primary = response.content[primary_start:primary_end]

    assert reverse("projects:government").encode() in primary
    assert reverse("projects:about").encode() in primary
    assert reverse("projects:community").encode() not in primary


@pytest.mark.django_db
@pytest.mark.unit
def test_home_calls_to_action_keep_visitors_in_the_active_language(client):
    """DSC-001/NFR-I18N-01: home-page catalog calls to action retain Nepali routing."""
    with override("ne"):
        response = client.get(reverse("projects:home"))
        hero_start = response.content.index(b'<section class="hero"')
        hero_end = response.content.index(b"</section>", hero_start)
        hero = response.content[hero_start:hero_end]

        assert f'href="{reverse("projects:government")}"'.encode() in hero
        assert f'href="{reverse("projects:about")}"'.encode() in hero
