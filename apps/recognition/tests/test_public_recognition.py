import pytest
from django.urls import reverse

from apps.projects.tests.factories import SuperAdminFactory
from apps.recognition.models import Badge
from apps.recognition.services import activate_policy

pytestmark = [pytest.mark.django_db, pytest.mark.unit]


def test_public_badges_expose_only_active_definitions_and_escaped_criteria(client):
    """REC-007/A3.7: public badge criteria are active-only and safely escaped."""
    active = Badge.objects.create(
        name="Public service contributor",
        slug="public-service-contributor",
        description="Verified public-interest work.",
        criteria_md="<script>alert(1)</script>\n\nOne accepted contribution.",
    )
    Badge.objects.create(name="Hidden", slug="hidden", is_active=False)

    listing = client.get(reverse("recognition:public_badges"))
    detail = client.get(reverse("recognition:public_badge_detail", args=[active.slug]))

    assert listing.status_code == 200
    assert active.name.encode() in listing.content
    assert b"Hidden" not in listing.content
    assert detail.status_code == 200
    assert b"<script>" not in detail.content
    assert b"&lt;script&gt;" in detail.content


def test_public_badge_detail_supports_the_models_unicode_slug_contract(client):
    """REC-007/NFR-I18N-01: public badge routes preserve Unicode slugs."""
    badge = Badge.objects.create(name="नेपाली योगदान", slug="नेपाली-योगदान")

    response = client.get(reverse("recognition:public_badge_detail", args=[badge.slug]))

    assert response.status_code == 200
    assert badge.name.encode() in response.content


def test_public_policy_discloses_active_version_and_rules(client):
    """REC-002/A3.7: the active scoring version and rules are public."""
    policy = activate_policy(SuperAdminFactory(), {"standard": 3})

    response = client.get(reverse("recognition:public_policy"))

    assert response.status_code == 200
    assert f"version {policy.version}".encode() in response.content
    assert b"standard" in response.content
    assert b">3<" in response.content
