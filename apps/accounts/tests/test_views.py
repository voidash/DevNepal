import pytest
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.accounts.models import MemberProfile, UserSession
from apps.accounts.tests.factories import MemberProfileFactory, UserFactory
from apps.ministries.tests.factories import MinistryPublisherFactory, SuperAdminFactory
from apps.ministries.tests.factories import UserFactory as PublisherUserFactory

pytestmark = pytest.mark.django_db


@pytest.mark.unit
def test_public_profile_exposes_only_public_payload(client):
    """MEM-003/MEM-005: legacy profile data is not rendered on GitHub-only profiles."""
    user = UserFactory(email="private@example.com")
    profile = MemberProfileFactory(
        user=user,
        headline="Civic technologist",
        location="Kathmandu",
        field_visibility={"location": "public"},
    )

    response = client.get(reverse("accounts:public_profile", kwargs={"username": user.username}))

    assert response.status_code == 200
    assert response.context["payload"]["headline"] == profile.headline
    assert response.context["payload"]["location"] == "Kathmandu"
    assert b"Civic technologist" not in response.content
    assert b"Kathmandu" not in response.content
    assert b"private@example.com" not in response.content


@pytest.mark.unit
def test_public_profile_exposes_a_prefilled_report_entrypoint(client):
    """MEM-010/ADM-003: a public profile links to a report form for that exact account."""
    user = UserFactory(username="reportable-member")
    MemberProfileFactory(user=user)
    content_type = ContentType.objects.get_for_model(user)

    response = client.get(reverse("accounts:public_profile", kwargs={"username": user.username}))

    assert response.status_code == 200
    expected = f"/en/reports/new/?content_type={content_type.pk}&amp;object_id={user.pk}"
    assert expected.encode() in response.content


@pytest.mark.unit
def test_profile_edit_updates_own_visibility_and_preview_does_not_save(client):
    """MEM-003/MEM-008: members edit only their profile and preview unsaved public changes."""
    user = UserFactory()
    profile = MemberProfileFactory(user=user, headline="Published")
    client.force_login(user)
    payload = {
        "headline": "Draft civic profile",
        "bio": "Works on open public services.",
        "location": "Lalitpur",
        "visibility_location": "public",
    }

    preview = client.post(reverse("accounts:profile_preview"), payload)

    profile.refresh_from_db()
    assert preview.status_code == 200
    assert preview.context["payload"]["headline"] == "Draft civic profile"
    assert preview.context["payload"]["location"] == "Lalitpur"
    assert profile.headline == "Published"

    saved = client.post(reverse("accounts:profile_edit"), payload)

    assert saved.status_code == 302
    profile.refresh_from_db()
    assert profile.headline == "Draft civic profile"
    assert profile.field_visibility["location"] == "public"


@pytest.mark.unit
def test_profile_preview_validates_without_saving_any_profile_changes(client):
    """MEM-008: preview validates all submitted fields without persisting valid draft changes."""
    user = UserFactory()
    profile = MemberProfileFactory(
        user=user,
        province="",
        preferred_language="en",
        availability="",
        directory_discoverable=False,
        leaderboard_opt_out=False,
        field_visibility={},
    )
    client.force_login(user)

    response = client.post(
        reverse("accounts:profile_preview"),
        {
            "headline": "Draft civic profile",
            "bio": "Draft biography",
            "location": "Lalitpur",
            "province": "bagmati",
            "preferred_language": "ne",
            "experience_band": "senior",
            "availability": "limited",
            "interests": "open data",
            "contribution_preferences": "documentation",
            "directory_discoverable": "on",
            "leaderboard_opt_out": "on",
            "visibility_location": "public",
            "visibility_province": "members",
            "visibility_education": "private",
            "visibility_links": "public",
            "visibility_skills": "members",
        },
    )

    profile.refresh_from_db()
    assert response.status_code == 200
    assert response.context["payload"]["headline"] == "Draft civic profile"
    assert response.context["payload"]["location"] == "Lalitpur"
    assert profile.headline == ""
    assert profile.field_visibility == {}
    assert profile.directory_discoverable is False
    assert profile.leaderboard_opt_out is False


@pytest.mark.unit
def test_profile_edit_returns_actionable_field_errors(client):
    """MEM-002/MEM-003: invalid submitted fields render named errors without saving."""
    user = UserFactory()
    profile = MemberProfileFactory(user=user, headline="Published")
    client.force_login(user)

    response = client.post(
        reverse("accounts:profile_edit"),
        {"headline": "x" * 201, "province": "not-a-province", "visibility_location": "invalid"},
    )

    profile.refresh_from_db()
    assert response.status_code == 400
    assert set(response.context["form"].errors) == {"headline", "province", "visibility_location"}
    assert profile.headline == "Published"


@pytest.mark.unit
def test_dashboard_requires_totp_for_ministry_publishers(client):
    """AUTH-005/AUTH-006: active publishers cannot access the dashboard without MFA."""
    publisher = PublisherUserFactory()
    MinistryPublisherFactory(user=publisher)
    TOTPDevice.objects.filter(user=publisher).delete()
    client.force_login(publisher)

    response = client.get(reverse("accounts:dashboard"))

    assert response.status_code == 302
    assert response.url == reverse("accounts:mfa_setup")


@pytest.mark.unit
def test_dashboard_allows_member_without_privileged_role(client):
    """AUTH-005: MFA enforcement applies to privileged roles, not ordinary member access."""
    client.force_login(UserFactory())

    response = client.get(reverse("accounts:dashboard"))

    assert response.status_code == 200
    assert reverse("accounts:session_list").encode() in response.content


@pytest.mark.unit
def test_dashboard_routes_verified_super_admin_to_pmo_operations(client, monkeypatch):
    """D5/AUTH-006: a PMO operator lands on platform operations, not member settings."""
    super_admin = SuperAdminFactory()
    client.force_login(super_admin)
    monkeypatch.setattr("apps.accounts.permissions.mfa_verified", lambda user: True)

    response = client.get(reverse("accounts:dashboard"))

    assert response.status_code == 302
    assert response.url == reverse("administration:console")


@pytest.mark.unit
def test_dashboard_routes_verified_publisher_to_ministry_authoring(client, monkeypatch):
    """C1/AUTH-006: an officer lands on ministry publishing, not member settings."""
    publisher = PublisherUserFactory()
    MinistryPublisherFactory(user=publisher)
    client.force_login(publisher)
    monkeypatch.setattr("apps.accounts.permissions.mfa_verified", lambda user: True)

    response = client.get(reverse("accounts:dashboard"))

    assert response.status_code == 302
    assert response.url == reverse("projects:authoring_dashboard")


@pytest.mark.unit
def test_dashboard_exposes_authenticated_member_tasks_with_mounted_routes(client):
    """AUTH-006/AUTH-007/AUTH-010/DSC-004/DSC-005: dashboard exposes accessible member tasks."""
    user = UserFactory(username="dashboard-member")
    client.force_login(user)

    response = client.get(reverse("accounts:dashboard"))

    assert response.status_code == 200
    assert response.context["profile"].user == user
    assert b'<h1 id="dashboard-heading">Dashboard</h1>' in response.content
    assert b'<nav aria-label="Member dashboard">' in response.content
    assert b'aria-describedby="deletion-notice"' in response.content
    for route in (
        reverse("accounts:profile_edit"),
        reverse("accounts:public_profile", kwargs={"username": user.username}),
        reverse("accounts:session_list"),
        reverse("projects:application_list"),
        reverse("projects:list"),
        reverse("accounts:privacy_export"),
        reverse("accounts:privacy_delete"),
    ):
        assert route.encode() in response.content
    assert b'<form action="/en/settings/privacy/delete/" method="post"' in response.content


@pytest.mark.unit
def test_totp_setup_verifies_publisher_and_unlocks_dashboard(client):
    """AUTH-005: a publisher confirms a TOTP token before gaining privileged dashboard access."""
    from django_otp.oath import totp

    publisher = PublisherUserFactory()
    MinistryPublisherFactory(user=publisher)
    TOTPDevice.objects.filter(user=publisher).delete()
    client.force_login(publisher)

    setup = client.post(reverse("accounts:mfa_setup"), {"action": "enroll"})
    device = TOTPDevice.objects.get(user=publisher)
    token = totp(
        device.bin_key,
        step=device.step,
        t0=device.t0,
        digits=device.digits,
        drift=device.drift,
    )
    confirmed = client.post(reverse("accounts:mfa_setup"), {"token": token})

    assert setup.status_code == 200
    assert confirmed.status_code == 302
    assert confirmed.url == reverse("accounts:dashboard")
    dashboard = client.get(reverse("accounts:dashboard"))
    assert dashboard.status_code == 302
    assert dashboard.url == reverse("projects:authoring_dashboard")


@pytest.mark.unit
def test_totp_setup_get_does_not_create_or_disclose_a_device_configuration(client):
    """AUTH-005: MFA setup GET is side-effect-free and never exposes an existing device secret."""
    publisher = PublisherUserFactory()
    MinistryPublisherFactory(user=publisher)
    TOTPDevice.objects.filter(user=publisher).delete()
    device = TOTPDevice.objects.create(user=publisher, name="devnepal")
    client.force_login(publisher)

    response = client.get(reverse("accounts:mfa_setup"))
    enrollment_retry = client.post(reverse("accounts:mfa_setup"), {"action": "enroll"})
    secret = device.config_url.split("secret=", maxsplit=1)[1].split("&", maxsplit=1)[0]

    assert response.status_code == 200
    assert TOTPDevice.objects.filter(user=publisher).count() == 1
    assert secret.encode() not in response.content
    assert response.context["config_url"] is None
    assert secret.encode() not in enrollment_retry.content
    assert enrollment_retry.context["config_url"] is None


@pytest.mark.unit
def test_totp_setup_verifies_an_existing_device_for_password_only_user(client):
    """AUTH-005: password-authenticated publishers can verify their existing TOTP device."""
    from django_otp.oath import totp

    publisher = PublisherUserFactory()
    MinistryPublisherFactory(user=publisher)
    TOTPDevice.objects.filter(user=publisher).delete()
    device = TOTPDevice.objects.create(user=publisher, name="devnepal")
    client.force_login(publisher)
    token = totp(
        device.bin_key,
        step=device.step,
        t0=device.t0,
        digits=device.digits,
        drift=device.drift,
    )

    response = client.post(reverse("accounts:mfa_setup"), {"token": token})

    assert response.status_code == 302
    assert response.url == reverse("accounts:dashboard")
    dashboard = client.get(reverse("accounts:dashboard"))
    assert dashboard.status_code == 302
    assert dashboard.url == reverse("projects:authoring_dashboard")


@pytest.mark.unit
def test_totp_setup_enrollment_requires_explicit_post(client):
    """AUTH-005: a publisher must explicitly submit MFA enrollment before a device is created."""
    publisher = PublisherUserFactory()
    MinistryPublisherFactory(user=publisher)
    TOTPDevice.objects.filter(user=publisher).delete()
    client.force_login(publisher)

    initial = client.get(reverse("accounts:mfa_setup"))
    assert initial.status_code == 200
    assert not TOTPDevice.objects.filter(user=publisher).exists()

    enrolled = client.post(reverse("accounts:mfa_setup"), {"action": "enroll"})

    device = TOTPDevice.objects.get(user=publisher)
    assert enrolled.status_code == 200
    assert enrolled.context["config_url"] == device.config_url


@pytest.mark.unit
def test_profile_edit_creates_a_profile_for_new_member(client):
    """MEM-002: profile editing establishes the member profile record when absent."""
    user = UserFactory()
    client.force_login(user)

    response = client.post(reverse("accounts:profile_edit"), {"headline": "New member"})

    assert response.status_code == 302
    assert MemberProfile.objects.get(user=user).headline == "New member"


@pytest.mark.unit
def test_local_login_authenticates_and_rejects_an_unsafe_return_url(client):
    """AUTH-001: password login creates a session and only follows safe local redirects."""
    user = UserFactory(username="demo-member")
    user.set_password("demo-password-2026")
    user.save(update_fields=["password"])

    page = client.get(reverse("accounts:login"))
    failed = client.post(
        reverse("accounts:login"),
        {"username": user.username, "password": "incorrect-password"},
    )
    authenticated = client.post(
        reverse("accounts:login"),
        {
            "username": user.username,
            "password": "demo-password-2026",
            "next": "https://untrusted.example/",
        },
    )

    assert page.status_code == 200
    assert b"Sign in" in page.content
    assert failed.status_code == 200
    assert b"Please enter a correct username and password" in failed.content
    assert authenticated.status_code == 302
    assert authenticated.url == reverse("accounts:dashboard")


@pytest.mark.unit
def test_local_login_respects_a_safe_local_return_url(client):
    """AUTH-001: password login returns members to the requested platform page."""
    user = UserFactory(username="returning-member")
    user.set_password("demo-password-2026")
    user.save(update_fields=["password"])
    destination = reverse("accounts:profile_edit")

    response = client.post(
        reverse("accounts:login"),
        {"username": user.username, "password": "demo-password-2026", "next": destination},
    )

    assert response.status_code == 302
    assert response.url == destination


@pytest.mark.unit
def test_local_login_and_logout_track_the_django_session(client):
    """AUTH-007: local authentication creates and revokes the server session ledger row."""
    user = UserFactory(username="session-member")
    user.set_password("demo-password-2026")
    user.save(update_fields=["password"])

    client.post(
        reverse("accounts:login"), {"username": user.username, "password": "demo-password-2026"}
    )
    session = UserSession.objects.get(user=user)
    response = client.post(reverse("accounts:logout"))

    session.refresh_from_db()
    assert response.status_code == 302
    assert session.last_activity is not None
    assert session.revoked_at is not None


@pytest.mark.unit
def test_member_can_view_and_revoke_only_their_own_sessions(client):
    """AUTH-007: session management lists a member's devices and blocks cross-account revocation."""
    user = UserFactory()
    own = UserSession.objects.create(user=user, session_key="own-session")
    other = UserSession.objects.create(user=UserFactory(), session_key="other-session")
    client.force_login(user)

    page = client.get(reverse("accounts:session_list"))
    denied = client.post(reverse("accounts:session_revoke", kwargs={"pk": other.pk}))
    revoked = client.post(reverse("accounts:session_revoke", kwargs={"pk": own.pk}))

    own.refresh_from_db()
    assert page.status_code == 200
    assert denied.status_code == 404
    assert revoked.status_code == 302
    assert own.revoked_at is not None


@pytest.mark.unit
def test_revoking_the_current_session_logs_the_member_out(client):
    """AUTH-007: revoking the current device terminates its Django authentication session."""
    user = UserFactory(username="current-session-member")
    user.set_password("demo-password-2026")
    user.save(update_fields=["password"])
    client.post(
        reverse("accounts:login"), {"username": user.username, "password": "demo-password-2026"}
    )
    session = UserSession.objects.get(user=user)

    response = client.post(reverse("accounts:session_revoke", kwargs={"pk": session.pk}))

    assert response.status_code == 302
    assert response.url == reverse("accounts:login")
    assert client.get(reverse("accounts:session_list")).status_code == 302


@pytest.mark.unit
def test_anonymous_account_pages_redirect_to_the_localized_login_page(client):
    """AUTH-001: protected account pages redirect to a resolvable localized sign-in route."""
    destination = reverse("accounts:profile_edit")

    response = client.get(destination)

    assert response.status_code == 302
    assert response.url.startswith(f"{reverse('accounts:login')}?next=")
    assert url_has_allowed_host_and_scheme(
        response.url.split("next=", maxsplit=1)[1], allowed_hosts={"testserver"}
    )


@pytest.mark.unit
def test_auth010_privacy_endpoints_are_authenticated_and_owner_only(client):
    """AUTH-010/AUTH-006: only the authenticated member can export or delete their own data."""
    user = UserFactory()
    other = UserFactory()

    anonymous = client.get(reverse("accounts:privacy_export"))
    client.force_login(user)
    exported = client.get(reverse("accounts:privacy_export"))
    deleted = client.post(reverse("accounts:privacy_delete"))

    assert anonymous.status_code == 302
    assert exported.status_code == 200
    assert exported.json()["account"]["username"] == user.username
    assert deleted.status_code == 204
    other.refresh_from_db()
    assert other.is_active is True


@pytest.mark.unit
def test_invalid_profile_visibility_does_not_break_the_public_profile(client):
    """MEM-003: invalid profile visibility is rejected without storing an unreadable profile."""
    user = UserFactory(username="validated-profile")
    profile = MemberProfileFactory(user=user, headline="Safe profile")
    client.force_login(user)

    response = client.post(
        reverse("accounts:profile_edit"),
        {"headline": "Unsafe profile", "visibility_location": "not-a-visibility"},
    )

    profile.refresh_from_db()
    public = client.get(reverse("accounts:public_profile", kwargs={"username": user.username}))
    assert response.status_code == 400
    assert profile.headline == "Safe profile"
    assert public.status_code == 200


@pytest.mark.unit
def test_profile_edit_preview_submits_the_current_edit_form(client):
    """MEM-008: the preview control submits the current unsaved profile fields."""
    client.force_login(UserFactory())

    response = client.get(reverse("accounts:profile_edit"))

    assert response.status_code == 200
    assert b'formaction="/en/settings/profile/preview/"' in response.content
