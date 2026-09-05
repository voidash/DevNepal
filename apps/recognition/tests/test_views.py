import pytest
from django.conf import settings
from django.test import override_settings
from django.urls import reverse
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.audit.models import AuditEvent
from apps.contributions.enums import VerificationStatus
from apps.contributions.tests.factories import ContributionRecordFactory
from apps.ministries.tests.factories import SuperAdminFactory, UserFactory
from apps.recognition.enums import AwardStatus
from apps.recognition.models import Badge, BadgeAward, ContributionScore
from apps.recognition.services import activate_policy
from apps.recognition.tests.factories import BadgeAwardFactory, BadgeFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def recognition_urlconf():
    with override_settings(ROOT_URLCONF="apps.recognition.tests.urls"):
        yield


def verify_mfa(client, user):
    client.force_login(user)
    device = TOTPDevice.objects.get(user=user)
    token = totp(
        device.bin_key,
        step=device.step,
        t0=device.t0,
        digits=device.digits,
        drift=device.drift,
    )
    response = client.post(reverse("accounts:mfa_setup"), {"token": token})
    assert response.status_code == 302


@pytest.mark.integration
def test_unverified_super_admin_cannot_access_recognition_administration(client):
    """AUTH-005/REC-002/REC-007: recognition administration requires verified MFA."""
    super_admin = SuperAdminFactory()
    super_admin.otp_device = None
    super_admin.is_verified = lambda: False
    client.force_login(super_admin)

    response = client.get(reverse("recognition:policy_create"))

    assert response.status_code == 302
    assert response.url == reverse("accounts:mfa_setup")


@pytest.mark.integration
def test_verified_super_admin_activates_policy_and_manages_badges(client):
    """REC-002/REC-007/SEC-008: verified Super Admin changes use audited recognition services."""
    super_admin = SuperAdminFactory()
    verify_mfa(client, super_admin)

    policy_response = client.post(
        reverse("recognition:policy_create"),
        {"rules": '{"standard": 3}', "document_url": "https://example.gov.np/policy"},
    )
    badge_response = client.post(
        reverse("recognition:badge_create"),
        {
            "name": "Documentation champion",
            "slug": "documentation-champion",
            "description": "Recognizes accepted documentation work.",
            "criteria_md": "Three accepted documentation contributions.",
            "criteria_version": 1,
            "kind": "contribution",
            "is_active": "on",
        },
    )

    badge = Badge.objects.get(slug="documentation-champion")
    update_response = client.post(
        reverse("recognition:badge_edit", kwargs={"slug": badge.slug}),
        {
            "name": badge.name,
            "slug": badge.slug,
            "description": "Recognizes verified documentation work.",
            "criteria_md": badge.criteria_md,
            "criteria_version": 2,
            "kind": badge.kind,
            "is_active": "on",
        },
    )

    badge.refresh_from_db()
    assert policy_response.status_code == 302
    assert badge_response.status_code == 302
    assert update_response.status_code == 302
    assert badge.criteria_version == 2
    assert AuditEvent.objects.filter(action="recognition.policy_activated").exists()
    assert AuditEvent.objects.filter(
        action="recognition.badge_created", object_id=str(badge.pk)
    ).exists()
    assert AuditEvent.objects.filter(
        action="recognition.badge_updated", object_id=str(badge.pk)
    ).exists()


@pytest.mark.integration
def test_member_sees_only_own_private_recognition_and_can_opt_out(client):
    """REC-004/REC-007: a member sees only their own private scores and badge history."""
    member = UserFactory()
    other = UserFactory()
    policy = activate_policy(SuperAdminFactory(), {"standard": 3})
    contribution = ContributionRecordFactory(contributor=member, status=VerificationStatus.ACCEPTED)
    ContributionScore.objects.create(contribution=contribution, policy=policy, points=3)
    own_award = BadgeAwardFactory(recipient=member)
    other_award = BadgeAwardFactory(recipient=other)
    client.force_login(member)

    profile_response = client.get(reverse("recognition:my_profile"))
    opt_out_response = client.post(reverse("recognition:opt_out"))

    assert profile_response.status_code == 200
    assert list(profile_response.context["scores"]) == [contribution.score]
    assert list(profile_response.context["awards"]) == [own_award]
    assert other_award not in profile_response.context["awards"]
    assert opt_out_response.status_code == 302
    assert member.profile.leaderboard_opt_out is True


@pytest.mark.integration
def test_public_leaderboard_explains_disabled_state_and_excludes_member_data(client):
    """REC-003/REC-004: disabled public rankings expose no member data and no dead route."""
    hidden_member = UserFactory()
    visible_member = UserFactory()
    policy = activate_policy(SuperAdminFactory(), {"standard": 3})
    hidden_contribution = ContributionRecordFactory(
        contributor=hidden_member, status=VerificationStatus.ACCEPTED
    )
    visible_contribution = ContributionRecordFactory(
        contributor=visible_member, status=VerificationStatus.ACCEPTED
    )
    ContributionScore.objects.create(contribution=hidden_contribution, policy=policy, points=9)
    ContributionScore.objects.create(contribution=visible_contribution, policy=policy, points=3)
    client.force_login(hidden_member)
    client.post(reverse("recognition:opt_out"))
    client.logout()

    disabled_response = client.get(reverse("recognition:leaderboard"))
    with override_settings(RECOGNITION_ENABLED=True):
        enabled_response = client.get(reverse("recognition:leaderboard"))

    assert settings.RECOGNITION_ENABLED is False
    assert disabled_response.status_code == 200
    assert disabled_response.context["public_leaderboard_available"] is False
    assert b"Public rankings are not enabled." in disabled_response.content
    assert hidden_member.username.encode() not in disabled_response.content
    assert visible_member.username.encode() not in disabled_response.content
    assert enabled_response.status_code == 200
    assert enabled_response.context["public_leaderboard_available"] is True
    assert hidden_member.username.encode() not in enabled_response.content
    assert visible_member.username.encode() in enabled_response.content


@pytest.mark.integration
def test_verified_super_admin_awards_existing_badge_to_member_with_reason(client):
    """REC-007/AUTH-005: a MFA-verified Super Admin awards a documented badge with a reason."""
    super_admin = SuperAdminFactory()
    member = UserFactory()
    badge = BadgeFactory()
    verify_mfa(client, super_admin)

    response = client.post(
        reverse("recognition:badge_award", kwargs={"slug": badge.slug}),
        {"username": member.username, "reason": "Sustained verified documentation work"},
    )

    award = BadgeAward.objects.get(badge=badge, recipient=member)
    assert response.status_code == 302
    assert response.url == reverse("recognition:badge_edit", kwargs={"slug": badge.slug})
    assert award.status == AwardStatus.ACTIVE
    assert award.issuer == super_admin
    event = AuditEvent.objects.get(action="recognition.badge_awarded", object_id=str(award.pk))
    assert event.after["reason"] == "Sustained verified documentation work"
    assert event.after["badge"] == badge.slug


@pytest.mark.integration
def test_badge_award_route_returns_404_for_unknown_member_or_badge(client):
    """REC-007: awarding an unknown member or badge is a 404, not a silent failure."""
    super_admin = SuperAdminFactory()
    badge = BadgeFactory()
    member = UserFactory()
    verify_mfa(client, super_admin)

    unknown_member_response = client.post(
        reverse("recognition:badge_award", kwargs={"slug": badge.slug}),
        {"username": "no-such-member", "reason": "Mistyped username"},
    )
    unknown_badge_response = client.get(
        reverse("recognition:badge_award", kwargs={"slug": "no-such-badge"})
    )

    assert unknown_member_response.status_code == 404
    assert unknown_badge_response.status_code == 404
    assert BadgeAward.objects.filter(recipient=member).count() == 0


@pytest.mark.integration
def test_badge_award_route_is_idempotent_for_an_existing_active_award(client):
    """REC-007: re-awarding an active badge keeps one award and one audit event."""
    super_admin = SuperAdminFactory()
    member = UserFactory()
    badge = BadgeFactory()
    verify_mfa(client, super_admin)

    first = client.post(
        reverse("recognition:badge_award", kwargs={"slug": badge.slug}),
        {"username": member.username, "reason": "First award decision"},
    )
    second = client.post(
        reverse("recognition:badge_award", kwargs={"slug": badge.slug}),
        {"username": member.username, "reason": "Duplicate submission"},
    )

    assert first.status_code == 302
    assert second.status_code == 302
    assert BadgeAward.objects.filter(badge=badge, recipient=member).count() == 1
    assert AuditEvent.objects.filter(action="recognition.badge_awarded").count() == 1


@pytest.mark.integration
def test_badge_award_route_requires_reason_and_rejects_inactive_badges(client):
    """REC-007: awards carry a reason and inactive badges cannot be awarded."""
    super_admin = SuperAdminFactory()
    member = UserFactory()
    badge = BadgeFactory(is_active=False)
    verify_mfa(client, super_admin)

    missing_reason = client.post(
        reverse("recognition:badge_award", kwargs={"slug": badge.slug}),
        {"username": member.username, "reason": ""},
    )
    inactive_badge = client.post(
        reverse("recognition:badge_award", kwargs={"slug": badge.slug}),
        {"username": member.username, "reason": "Reason provided"},
    )

    assert missing_reason.status_code == 400
    assert inactive_badge.status_code == 400
    assert BadgeAward.objects.filter(recipient=member).count() == 0


@pytest.mark.integration
def test_badge_award_and_revoke_routes_require_verified_super_admin(client):
    """AUTH-005/REC-007: award and revocation routes are MFA-gated Super Admin surfaces."""
    unverified_admin = SuperAdminFactory()
    unverified_admin.otp_device = None
    unverified_admin.is_verified = lambda: False
    member = UserFactory()
    badge = BadgeFactory()
    award = BadgeAwardFactory(badge=badge, recipient=member)
    client.force_login(unverified_admin)

    award_response = client.post(
        reverse("recognition:badge_award", kwargs={"slug": badge.slug}),
        {"username": member.username, "reason": "Unverified attempt"},
    )
    revoke_response = client.post(
        reverse("recognition:award_revoke", kwargs={"pk": award.pk}),
        {"reason": "Unverified attempt"},
    )

    assert award_response.status_code == 302
    assert award_response.url == reverse("accounts:mfa_setup")
    assert revoke_response.status_code == 302
    assert revoke_response.url == reverse("accounts:mfa_setup")
    assert BadgeAward.objects.get(pk=award.pk).status == AwardStatus.ACTIVE

    member_client_user = UserFactory()
    client.force_login(member_client_user)
    member_award_response = client.post(
        reverse("recognition:badge_award", kwargs={"slug": badge.slug}),
        {"username": member.username, "reason": "Member attempt"},
    )
    member_revoke_response = client.post(
        reverse("recognition:award_revoke", kwargs={"pk": award.pk}),
        {"reason": "Member attempt"},
    )

    assert member_award_response.status_code == 403
    assert member_revoke_response.status_code == 403


@pytest.mark.integration
def test_verified_super_admin_revokes_award_with_reason_and_audit(client):
    """REC-005/REC-007: revocation records the reason, revoker, and audit evidence."""
    super_admin = SuperAdminFactory()
    member = UserFactory()
    badge = BadgeFactory()
    award = BadgeAwardFactory(badge=badge, recipient=member)
    verify_mfa(client, super_admin)

    response = client.post(
        reverse("recognition:award_revoke", kwargs={"pk": award.pk}),
        {"reason": "Evidence was invalidated"},
    )

    award.refresh_from_db()
    assert response.status_code == 302
    assert response.url == reverse("recognition:badge_edit", kwargs={"slug": badge.slug})
    assert award.status == AwardStatus.REVOKED
    assert award.revocation_reason == "Evidence was invalidated"
    assert award.revoked_by == super_admin
    assert award.revoked_at is not None
    assert AuditEvent.objects.filter(
        action="recognition.badge_revoked", object_id=str(award.pk)
    ).exists()


@pytest.mark.integration
def test_award_revoke_route_404s_unknown_award_and_requires_reason(client):
    """REC-007: revoking an unknown award is a 404; an empty reason is rejected."""
    super_admin = SuperAdminFactory()
    member = UserFactory()
    award = BadgeAwardFactory(recipient=member)
    verify_mfa(client, super_admin)

    unknown_response = client.post(
        reverse("recognition:award_revoke", kwargs={"pk": award.pk + 9999}),
        {"reason": "Unknown award"},
    )
    missing_reason_response = client.post(
        reverse("recognition:award_revoke", kwargs={"pk": award.pk}),
        {"reason": "   "},
    )

    award.refresh_from_db()
    assert unknown_response.status_code == 404
    assert missing_reason_response.status_code == 400
    assert award.status == AwardStatus.ACTIVE


@pytest.mark.integration
def test_award_revoke_is_idempotent_for_an_already_revoked_award(client):
    """REC-005/REC-007: revoking twice keeps one revocation audit event."""
    super_admin = SuperAdminFactory()
    award = BadgeAwardFactory()
    verify_mfa(client, super_admin)

    first = client.post(
        reverse("recognition:award_revoke", kwargs={"pk": award.pk}),
        {"reason": "Evidence invalidated"},
    )
    second = client.post(
        reverse("recognition:award_revoke", kwargs={"pk": award.pk}),
        {"reason": "Duplicate revocation"},
    )

    assert first.status_code == 302
    assert second.status_code == 302
    assert AuditEvent.objects.filter(action="recognition.badge_revoked").count() == 1


@pytest.mark.integration
def test_badge_administration_pages_surface_awards_and_award_entry(client):
    """REC-007: admin badge pages list awards and link to the award and anomaly surfaces."""
    super_admin = SuperAdminFactory()
    member = UserFactory()
    badge = BadgeFactory()
    award = BadgeAwardFactory(badge=badge, recipient=member)
    verify_mfa(client, super_admin)

    list_response = client.get(reverse("recognition:badge_list"))
    edit_response = client.get(reverse("recognition:badge_edit", kwargs={"slug": badge.slug}))
    award_page = client.get(reverse("recognition:badge_award", kwargs={"slug": badge.slug}))

    assert list_response.status_code == 200
    assert edit_response.status_code == 200
    assert award_page.status_code == 200
    assert list(award_page.context["form"].fields) == ["username", "reason"]
    assert award in list(edit_response.context["awards"])
