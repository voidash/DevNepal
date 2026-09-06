from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.administration.enums import ChangeStatus, GrantAction
from apps.administration.models import SuperAdminGrant
from apps.administration.services import (
    ChangeNotPendingError,
    GrantExpiredError,
    LastSuperAdminError,
    MissingChangeReasonError,
    RedundantGrantError,
    SelfApprovalError,
    confirm_super_admin_grant,
    propose_super_admin_grant,
    revoke_super_admin,
    super_admin_roster,
)
from apps.audit.models import AuditEvent
from apps.audit.tests.factories import UserFactory
from apps.ministries.tests.factories import SuperAdminFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _privileged_mfa_bypass(settings):
    settings.PRIVILEGED_MFA_BYPASS = True


@pytest.mark.integration
def test_a_proposed_grant_does_not_make_anyone_a_super_admin():
    """AUTH-003/D5.8: a grant is not effective on the proposer's authority alone."""
    member = UserFactory()

    grant = propose_super_admin_grant(SuperAdminFactory(), member, reason="Joining the PMO team.")

    member.refresh_from_db()
    assert grant.status == ChangeStatus.PENDING
    assert member.is_superuser is False
    assert grant.expires_at > timezone.now()


@pytest.mark.integration
def test_a_second_super_admin_confirms_the_grant():
    """AUTH-003/D5.8: a different Super Admin confirms and the role takes effect."""
    proposer, approver = SuperAdminFactory(), SuperAdminFactory()
    member = UserFactory()
    grant = propose_super_admin_grant(proposer, member, reason="Joining the PMO team.")

    confirm_super_admin_grant(approver, grant)

    member.refresh_from_db()
    grant.refresh_from_db()
    assert member.is_superuser is True
    assert member.is_staff is True
    assert grant.status == ChangeStatus.APPLIED
    assert grant.approved_by == approver


@pytest.mark.integration
def test_the_proposer_cannot_confirm_their_own_grant():
    """AUTH-003/D5.8/ADM-008: self-confirmation is refused and the attempt is audited."""
    proposer = SuperAdminFactory()
    member = UserFactory()
    grant = propose_super_admin_grant(proposer, member, reason="Joining the PMO team.")

    with pytest.raises(SelfApprovalError):
        confirm_super_admin_grant(proposer, grant)

    member.refresh_from_db()
    assert member.is_superuser is False
    assert AuditEvent.objects.filter(
        action="administration.super_admin_grant_confirmed", result="denied"
    ).exists()


@pytest.mark.integration
def test_a_grant_lapses_when_nobody_confirms_within_the_window():
    """AUTH-003/D5.8: an unconfirmed grant expires after 24 hours instead of lingering."""
    proposer, approver = SuperAdminFactory(), SuperAdminFactory()
    member = UserFactory()
    grant = propose_super_admin_grant(proposer, member, reason="Joining the PMO team.")
    SuperAdminGrant.objects.filter(pk=grant.pk).update(
        expires_at=timezone.now() - timedelta(minutes=1)
    )
    grant.refresh_from_db()

    with pytest.raises(GrantExpiredError):
        confirm_super_admin_grant(approver, grant)

    member.refresh_from_db()
    grant.refresh_from_db()
    assert member.is_superuser is False
    assert grant.status == ChangeStatus.WITHDRAWN


@pytest.mark.integration
def test_a_confirmed_grant_cannot_be_confirmed_again():
    """AUTH-003/D5.8: an applied grant is closed to further decisions."""
    proposer, approver = SuperAdminFactory(), SuperAdminFactory()
    grant = propose_super_admin_grant(proposer, UserFactory(), reason="Joining the PMO team.")
    confirm_super_admin_grant(approver, grant)

    with pytest.raises(ChangeNotPendingError):
        confirm_super_admin_grant(SuperAdminFactory(), grant)


@pytest.mark.integration
def test_a_stale_pending_grant_cannot_be_confirmed_after_another_request_applies_it():
    """AUTH-003/D5.8: confirmation rechecks locked database state, not a stale object."""
    proposer, first_approver, late_approver = (
        SuperAdminFactory(),
        SuperAdminFactory(),
        SuperAdminFactory(),
    )
    grant = propose_super_admin_grant(proposer, UserFactory(), reason="Joining the PMO team.")
    stale_grant = SuperAdminGrant.objects.get(pk=grant.pk)

    confirm_super_admin_grant(first_approver, grant)

    with pytest.raises(ChangeNotPendingError):
        confirm_super_admin_grant(late_approver, stale_grant)


@pytest.mark.integration
def test_granting_someone_who_already_holds_the_role_is_refused():
    """AUTH-003/D5.8: a redundant grant is rejected rather than recorded."""
    with pytest.raises(RedundantGrantError):
        propose_super_admin_grant(SuperAdminFactory(), SuperAdminFactory(), reason="Again.")


@pytest.mark.integration
def test_a_grant_records_why_it_was_proposed():
    """AUTH-003/ADM-008/D5.8: a grant without a stated reason is refused."""
    with pytest.raises(MissingChangeReasonError):
        propose_super_admin_grant(SuperAdminFactory(), UserFactory(), reason="  ")


@pytest.mark.integration
def test_revoking_takes_effect_immediately_and_ends_sessions():
    """AUTH-003/AUTH-007/D5.8: revocation is immediate and the person's sessions end."""
    from apps.accounts.models import UserSession

    actor, subject = SuperAdminFactory(), SuperAdminFactory()
    UserSession.objects.create(session_key="abc123", user=subject, device_label="Firefox")

    revoke_super_admin(actor, subject, reason="Left the PMO.")

    subject.refresh_from_db()
    assert subject.is_superuser is False
    assert subject.is_staff is False
    assert UserSession.objects.get(session_key="abc123").revoked_at is not None


@pytest.mark.integration
def test_a_revoked_super_admin_keeps_their_audit_entries():
    """AUTH-003/ADM-008/D5.8: revocation never rewrites what that person already did."""
    actor, subject = SuperAdminFactory(), SuperAdminFactory()
    AuditEvent.objects.create(actor=subject, action="project.publish", source="web")

    revoke_super_admin(actor, subject, reason="Left the PMO.")

    assert AuditEvent.objects.filter(actor=subject, action="project.publish").exists()


@pytest.mark.integration
def test_the_last_super_admin_cannot_be_revoked():
    """AUTH-003/D5.8: the platform never ends up with nobody holding Super Admin."""
    only_admin = SuperAdminFactory()

    with pytest.raises(LastSuperAdminError):
        revoke_super_admin(only_admin, only_admin, reason="Standing down.")

    only_admin.refresh_from_db()
    assert only_admin.is_superuser is True


@pytest.mark.integration
def test_the_roster_reports_mfa_grant_attribution_and_open_sessions():
    """AUTH-003/AUTH-007/D5.8: the roster names how each admin verifies and who granted them."""
    from django_otp.plugins.otp_totp.models import TOTPDevice

    proposer, approver = SuperAdminFactory(), SuperAdminFactory()
    member = UserFactory()
    TOTPDevice.objects.create(user=member, name="devnepal", confirmed=True)
    grant = propose_super_admin_grant(proposer, member, reason="Joining the PMO team.")
    confirm_super_admin_grant(approver, grant)

    entry = next(row for row in super_admin_roster() if row["user"] == member)

    assert entry["mfa"] == "TOTP"
    assert entry["grant"].proposed_by == proposer
    assert entry["grant"].approved_by == approver
    assert entry["active_sessions"] == 0


@pytest.mark.integration
def test_a_member_cannot_reach_privileged_access(client):
    """SEC-005/D5.8: the privileged access page is Super Admin only."""
    client.force_login(UserFactory())

    assert client.get(reverse("administration:privileged_access")).status_code == 403


@pytest.mark.integration
def test_the_page_proposes_a_grant_and_a_second_admin_confirms_it(client):
    """AUTH-003/D5.8: the page routes a Super Admin grant through two named people."""
    proposer, approver = SuperAdminFactory(), SuperAdminFactory()
    member = UserFactory()

    client.force_login(proposer)
    client.post(
        reverse("administration:privileged_access"),
        {"username": member.username, "reason": "Joining the PMO team."},
    )
    member.refresh_from_db()
    assert member.is_superuser is False

    grant = SuperAdminGrant.objects.get(status=ChangeStatus.PENDING, action=GrantAction.GRANT)
    client.force_login(approver)
    response = client.post(reverse("administration:super_admin_grant_confirm", args=[grant.pk]))

    member.refresh_from_db()
    assert response.status_code == 302
    assert member.is_superuser is True
