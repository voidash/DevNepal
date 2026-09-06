import pytest
from django.urls import reverse

from apps.administration.enums import ChangeStatus
from apps.administration.models import FeatureFlag, FeatureFlagChange
from apps.administration.services import (
    ChangeNotPendingError,
    FourEyesRequiredError,
    MissingChangeReasonError,
    SelfApprovalError,
    approve_feature_flag_change,
    request_feature_flag_change,
    set_feature_flag,
)
from apps.administration.tests.factories import FeatureFlagFactory, MemberFacingFlagFactory
from apps.audit.models import AuditEvent
from apps.ministries.tests.factories import SuperAdminFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _privileged_mfa_bypass(settings):
    settings.PRIVILEGED_MFA_BYPASS = True


@pytest.mark.integration
def test_a_member_impacting_switch_is_not_applied_by_the_proposer():
    """ADM-001/D5.7: a change members can see waits for a second Super Admin."""
    flag = MemberFacingFlagFactory(key="public-leaderboard", is_enabled=False)

    change = request_feature_flag_change(
        SuperAdminFactory(), flag, is_enabled=True, reason="Policy v1.2 approved."
    )

    flag.refresh_from_db()
    assert change.status == ChangeStatus.PENDING
    assert flag.is_enabled is False
    assert flag.version == 0


@pytest.mark.integration
def test_a_second_super_admin_confirms_and_the_switch_applies():
    """ADM-001/D5.7: a different Super Admin confirms, and the change takes effect."""
    proposer, approver = SuperAdminFactory(), SuperAdminFactory()
    flag = MemberFacingFlagFactory(key="facebook-sign-in", is_enabled=False)
    change = request_feature_flag_change(
        proposer, flag, is_enabled=True, reason="Provider assessment complete."
    )

    approve_feature_flag_change(approver, change)

    flag.refresh_from_db()
    change.refresh_from_db()
    assert flag.is_enabled is True
    assert flag.version == 1
    assert change.status == ChangeStatus.APPLIED
    assert change.approved_by == approver
    assert change.is_four_eyes is True


@pytest.mark.integration
def test_the_proposer_cannot_confirm_their_own_change_and_it_is_audited():
    """ADM-001/D5.7/ADM-008: self-approval is refused and the attempt is recorded."""
    proposer = SuperAdminFactory()
    flag = MemberFacingFlagFactory(key="auto-hide", is_enabled=False)
    change = request_feature_flag_change(
        proposer, flag, is_enabled=True, reason="Trialling automatic hiding."
    )

    with pytest.raises(SelfApprovalError):
        approve_feature_flag_change(proposer, change)

    flag.refresh_from_db()
    assert flag.is_enabled is False
    assert AuditEvent.objects.filter(
        action="administration.feature_flag_change_approve", result="denied"
    ).exists()


@pytest.mark.integration
def test_a_confirmed_change_cannot_be_confirmed_twice():
    """ADM-001/D5.7: an applied change is closed to further decisions."""
    proposer, approver = SuperAdminFactory(), SuperAdminFactory()
    flag = MemberFacingFlagFactory(is_enabled=False)
    change = request_feature_flag_change(proposer, flag, is_enabled=True, reason="Approved.")
    approve_feature_flag_change(approver, change)

    with pytest.raises(ChangeNotPendingError):
        approve_feature_flag_change(SuperAdminFactory(), change)


@pytest.mark.integration
def test_a_stale_pending_change_cannot_be_confirmed_after_another_request_applies_it():
    """ADM-001/D5.7: approval rechecks locked database state, not a stale object."""
    proposer, first_approver, late_approver = (
        SuperAdminFactory(),
        SuperAdminFactory(),
        SuperAdminFactory(),
    )
    flag = MemberFacingFlagFactory(is_enabled=False)
    change = request_feature_flag_change(proposer, flag, is_enabled=True, reason="Approved.")
    stale_change = FeatureFlagChange.objects.get(pk=change.pk)

    approve_feature_flag_change(first_approver, change)

    with pytest.raises(ChangeNotPendingError):
        approve_feature_flag_change(late_approver, stale_change)


@pytest.mark.integration
def test_an_operator_switch_applies_without_a_second_approver():
    """ADM-001/D5.7: a switch members cannot see stays a single-admin decision."""
    flag = FeatureFlagFactory(key="readiness-blocks-submit", is_enabled=False)

    change = request_feature_flag_change(
        SuperAdminFactory(), flag, is_enabled=True, reason="Advisory elsewhere."
    )

    flag.refresh_from_db()
    assert change.status == ChangeStatus.APPLIED
    assert flag.is_enabled is True
    assert flag.version == 1


@pytest.mark.integration
def test_the_direct_path_refuses_a_member_impacting_switch():
    """ADM-001/D5.7: the single-admin helper cannot be used to bypass the four-eyes rule."""
    flag = MemberFacingFlagFactory(is_enabled=False)

    with pytest.raises(FourEyesRequiredError):
        set_feature_flag(SuperAdminFactory(), flag, is_enabled=True, reason="Trying to skip.")

    flag.refresh_from_db()
    assert flag.is_enabled is False


@pytest.mark.integration
def test_every_change_records_a_reason():
    """ADM-001/ADM-008/D5.7: a configuration change without a reason is refused."""
    flag = FeatureFlagFactory()

    with pytest.raises(MissingChangeReasonError):
        request_feature_flag_change(SuperAdminFactory(), flag, is_enabled=True, reason="   ")


@pytest.mark.integration
def test_each_change_is_versioned_and_attributed():
    """D5.7/ADM-008: the change log states the version, the reason and both named admins."""
    proposer, approver = SuperAdminFactory(), SuperAdminFactory()
    flag = MemberFacingFlagFactory(key="members-only-tier", is_enabled=False)

    first = request_feature_flag_change(proposer, flag, is_enabled=True, reason="Enable for beta.")
    approve_feature_flag_change(approver, first)
    second = request_feature_flag_change(
        approver, flag, is_enabled=False, reason="Re-evaluate after beta."
    )
    approve_feature_flag_change(proposer, second)

    versions = list(
        FeatureFlagChange.objects.filter(flag=flag)
        .order_by("version")
        .values_list("version", "reason", "status")
    )
    flag.refresh_from_db()
    assert versions == [
        (1, "Enable for beta.", ChangeStatus.APPLIED),
        (2, "Re-evaluate after beta.", ChangeStatus.APPLIED),
    ]
    assert flag.version == 2
    assert flag.is_enabled is False


@pytest.mark.integration
def test_the_page_holds_a_member_impacting_change_and_a_second_admin_confirms_it(client):
    """ADM-001/D5.7: the flag page routes a member-impacting change through two people."""
    proposer, approver = SuperAdminFactory(), SuperAdminFactory()
    MemberFacingFlagFactory(key="public-leaderboard", is_enabled=False)

    client.force_login(proposer)
    client.post(
        reverse("administration:feature_flag_change", args=["public-leaderboard"]),
        {"reason": "Policy v1.2 approved."},
    )

    assert FeatureFlag.objects.get(key="public-leaderboard").is_enabled is False
    pending = FeatureFlagChange.objects.get(status=ChangeStatus.PENDING)

    client.force_login(approver)
    response = client.post(reverse("administration:feature_flag_approve", args=[pending.pk]))

    assert response.status_code == 302
    assert FeatureFlag.objects.get(key="public-leaderboard").is_enabled is True


@pytest.mark.integration
def test_a_change_submitted_without_a_reason_is_rejected_by_the_page(client):
    """ADM-001/ADM-008/D5.7: the page will not record a switch change with no stated reason."""
    FeatureFlagFactory(key="no-reason-given", is_enabled=False)
    client.force_login(SuperAdminFactory())

    client.post(reverse("administration:feature_flag_change", args=["no-reason-given"]), {})

    assert FeatureFlag.objects.get(key="no-reason-given").is_enabled is False
    assert not FeatureFlagChange.objects.exists()
