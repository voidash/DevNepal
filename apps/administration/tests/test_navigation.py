import pytest
from django.urls import reverse

from apps.audit.tests.factories import UserFactory
from apps.ministries.tests.factories import (
    MinistryPublisherFactory,
    SuperAdminFactory,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _privileged_mfa_bypass(settings):
    settings.PRIVILEGED_MFA_BYPASS = True


SUPER_ADMIN_DESTINATIONS = (
    "administration:console",
    "projects:review_queue",
    "moderation:case_queue",
    "moderation:community_health",
    "contributions:verification_queue",
    "ministries:organization_list",
    "taxonomy:skill_suggestion_review_list",
    "recognition:badge_list",
    "administration:feature_flags",
    "audit:ops_dashboard",
    "audit:audit_log",
)


@pytest.mark.integration
def test_public_visitor_sees_no_administrative_navigation(client):
    """SEC-005: administrative destinations are not advertised to the public."""
    content = client.get(reverse("projects:home")).content.decode()

    assert "dn-admin-bar" not in content
    for name in SUPER_ADMIN_DESTINATIONS:
        assert reverse(name) not in content


@pytest.mark.integration
def test_member_sees_no_administrative_navigation(client):
    """SEC-005: an authenticated member is offered no privileged destination."""
    client.force_login(UserFactory())

    content = client.get(reverse("projects:home")).content.decode()

    assert "dn-admin-bar" not in content


@pytest.mark.integration
def test_super_admin_reaches_every_privileged_surface_from_any_page(client):
    """ADM-002/NFR-A11Y-01: the shared shell links a Super Admin to all of their work."""
    client.force_login(SuperAdminFactory())

    content = client.get(reverse("projects:home")).content.decode()

    assert "dn-admin-bar" in content
    for name in SUPER_ADMIN_DESTINATIONS:
        assert reverse(name) in content


@pytest.mark.integration
def test_ministry_publisher_reaches_their_publishing_dashboard(client):
    """GOV-004/AUTH-006: a named publisher has a signed-in entry point to their own work."""
    publisher = MinistryPublisherFactory()
    client.force_login(publisher.user)

    content = client.get(reverse("projects:home")).content.decode()

    assert reverse("projects:authoring_dashboard") in content
    assert reverse("audit:my_actions") in content
    assert f'href="{reverse("audit:audit_log")}"' not in content
