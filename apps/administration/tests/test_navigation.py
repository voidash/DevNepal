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
def test_super_admin_does_not_receive_privileged_navigation_in_the_public_shell(client):
    """SEC-005/DSC-001: privileged work is not mixed into the visitor-oriented shell."""
    client.force_login(SuperAdminFactory())

    content = client.get(reverse("projects:home")).content.decode()

    assert "dn-admin-bar" not in content
    for name in SUPER_ADMIN_DESTINATIONS:
        assert reverse(name) not in content


@pytest.mark.integration
def test_ministry_publisher_reaches_their_publishing_dashboard(client):
    """GOV-004/AUTH-006: a named publisher retains their one relevant authoring entry point."""
    publisher = MinistryPublisherFactory()
    client.force_login(publisher.user)

    content = client.get(reverse("projects:home")).content.decode()

    assert reverse("projects:authoring_dashboard") in content
    assert reverse("audit:my_actions") not in content
    assert f'href="{reverse("audit:audit_log")}"' not in content


@pytest.mark.integration
def test_a_legacy_signed_in_member_does_not_expand_the_minimal_shell(client):
    """AUTH-006/DSC-001: legacy member identity is absent from the GitHub-first shell."""
    member = UserFactory(username="sabina-thapa", first_name="Sabina", last_name="Thapa")
    client.force_login(member)

    content = client.get(reverse("projects:home")).content.decode()

    assert "Sabina Thapa" not in content
    assert reverse("accounts:dashboard") not in content


@pytest.mark.integration
def test_a_ministry_publisher_without_a_full_name_is_identified_by_username(client):
    """GIT-002/AUTH-006: the ministry workspace identifies its authenticated operator."""
    publisher = MinistryPublisherFactory(
        user=UserFactory(username="octocat-np", first_name="", last_name="")
    )
    client.force_login(publisher.user)

    content = client.get(reverse("projects:home")).content.decode()

    assert "Ministry: octocat-np" in content


@pytest.mark.integration
def test_a_public_visitor_is_not_greeted(client):
    """SEC-005: no name is shown before anyone signs in."""
    content = client.get(reverse("projects:home")).content.decode()

    assert "dn-greeting" not in content
    assert "Hi " not in content
