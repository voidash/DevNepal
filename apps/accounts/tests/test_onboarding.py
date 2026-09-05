"""Prototype B1.1-B1.5 account onboarding integration coverage."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.accounts.models import MemberProfile
from apps.accounts.tests.factories import UserFactory
from apps.audit.models import AuditEvent
from apps.taxonomy.tests.factories import SkillFactory

pytestmark = pytest.mark.django_db


@pytest.mark.unit
def test_password_signup_resumes_the_persisted_profile_onboarding_after_sign_in(client):
    """AUTH-001/MEM-002: a new local member signs in before profile setup begins."""
    signup = client.post(
        reverse("accounts:signup"),
        {
            "username": "onboarding-member",
            "email": "onboarding@example.com",
            "password1": "winter-river-2026",
            "password2": "winter-river-2026",
        },
    )

    assert signup.status_code == 302
    assert signup.url == reverse("accounts:login")
    member = get_user_model().objects.get(username="onboarding-member")
    assert member.profile.onboarding_completed is False

    signed_in = client.post(
        reverse("accounts:login"),
        {"username": "onboarding-member", "password": "winter-river-2026"},
    )

    assert signed_in.status_code == 302
    assert signed_in.url == reverse("accounts:onboarding_profile")


@pytest.mark.unit
def test_onboarding_persists_profile_visibility_skip_and_explicit_publish(client):
    """MEM-002/MEM-003/MEM-008/GIT-002: each B1 step persists only its real state."""
    skill = SkillFactory(name="Accessibility testing", slug="accessibility-testing")
    member = UserFactory(username="onboarding-flow", email="flow@example.com")
    profile = MemberProfile.objects.create(user=member)
    client.force_login(member)

    profile_step = client.post(
        reverse("accounts:onboarding_profile"),
        {
            "skills": [str(skill.pk)],
            "experience_band": "3-5 years",
            "availability": "limited",
            "location": "Hetauda",
            "province": "bagmati",
            "headline": "Frontend developer",
            "contribution_preferences": "Engineering and localization",
            "interests": "Accessibility and public health",
        },
    )
    profile.refresh_from_db()

    assert profile_step.status_code == 302
    assert profile_step.url == reverse("accounts:onboarding_visibility")
    assert profile.headline == "Frontend developer"
    assert profile.location == "Hetauda"
    assert member.skills.filter(skill=skill).exists()

    visibility_step = client.post(
        reverse("accounts:onboarding_visibility"),
        {
            "visibility_skills": "public",
            "visibility_location": "public",
            "visibility_province": "private",
            "visibility_education": "private",
            "visibility_links": "private",
            "directory_discoverable": "on",
        },
    )
    profile.refresh_from_db()

    assert visibility_step.status_code == 302
    assert visibility_step.url == reverse("accounts:onboarding_github")
    assert profile.field_visibility["skills"] == "public"
    assert profile.field_visibility["location"] == "public"
    assert profile.directory_discoverable is True

    skipped = client.post(reverse("accounts:onboarding_github_skip"))
    profile.refresh_from_db()

    assert skipped.status_code == 302
    assert skipped.url == reverse("accounts:onboarding_preview")
    assert profile.github_onboarding_skipped is True
    assert AuditEvent.objects.filter(
        action="account.onboarding_github_skipped", actor=member
    ).exists()

    preview = client.get(reverse("accounts:onboarding_preview"))
    assert preview.status_code == 200
    assert b"Frontend developer" in preview.content
    assert b"flow@example.com" not in preview.content

    published = client.post(reverse("accounts:onboarding_publish"))
    profile.refresh_from_db()

    assert published.status_code == 302
    assert published.url == reverse("accounts:dashboard")
    assert profile.onboarding_completed is True
    assert AuditEvent.objects.filter(action="account.onboarding_published", actor=member).exists()


@pytest.mark.unit
def test_onboarding_github_screen_is_honest_when_oauth_is_unavailable(client, settings):
    """AUTH-002/GIT-010: an unconfigured GitHub provider cannot be presented as connectable."""
    settings.GITHUB_CLIENT_ID = ""
    settings.GITHUB_CLIENT_SECRET = ""
    member = UserFactory()
    MemberProfile.objects.create(user=member)
    client.force_login(member)

    response = client.get(reverse("accounts:onboarding_github"))

    assert response.status_code == 200
    assert b"GitHub connection is not available" in response.content
    assert reverse("accounts:github_connect").encode() not in response.content
    assert client.get(reverse("accounts:onboarding_github_skip")).status_code == 405
