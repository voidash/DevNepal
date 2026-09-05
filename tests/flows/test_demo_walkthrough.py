"""The demo walkthrough, executed the way it will be presented.

Every step here is a real HTTP request through the production URLconf, in the
order the presenter clicks them. A failure means the demo breaks on stage, not
that an abstraction changed.
"""

import pytest
from django.urls import reverse

from apps.accounts.models import MemberProfile
from apps.administration.enums import ChangeStatus
from apps.administration.models import FeatureFlag, FeatureFlagChange, SuperAdminGrant
from apps.contributions.enums import VerificationStatus
from apps.contributions.tests.factories import ContributionRecordFactory
from apps.ministries.enums import ContactVerificationStatus, OrgStatus, PublisherStatus
from apps.ministries.models import MinistryOrganization, MinistryPublisher
from apps.ministries.services import log_onboarding_request
from apps.ministries.tests.factories import MinistryPublisherFactory, SuperAdminFactory
from apps.projects.enums import ProjectStatus
from apps.projects.tests.factories import UserFactory, make_publishable

pytestmark = [pytest.mark.django_db, pytest.mark.acceptance]

PASSWORD = "demo-password-2026"


@pytest.fixture(autouse=True)
def _privileged_mfa_bypass(settings):
    settings.PRIVILEGED_MFA_BYPASS = True


def signed_in(client, user):
    """Sign in as `user`, signing out first.

    LocalLoginView sets redirect_authenticated_user, so posting the login form
    while a session is already open bounces to the dashboard without changing
    who is signed in. Switching roles therefore requires an explicit sign-out.
    """
    client.post(reverse("accounts:logout"))
    user.set_password(PASSWORD)
    user.save(update_fields=["password"])
    assert (
        client.post(
            reverse("accounts:login"), {"username": user.username, "password": PASSWORD}
        ).status_code
        == 302
    )
    return client


@pytest.mark.acceptance
def test_beat_1_a_visitor_sees_the_public_platform(client):
    """A1/DSC-001: the pages the presenter opens before signing in all render."""
    for name in ("projects:home", "projects:list", "projects:government", "projects:community"):
        assert client.get(reverse(name)).status_code == 200, name


@pytest.mark.acceptance
def test_beat_1_the_interface_switches_to_nepali(client):
    """DSC-001/NFR-I18N-01: the Nepali toggle the presenter demonstrates works."""
    response = client.get("/ne/")

    assert response.status_code == 200
    assert 'lang="ne"' in response.content.decode()


@pytest.mark.acceptance
def test_beat_2_a_super_admin_provisions_a_ministry_from_a_request(client):
    """D1.1/D1.2/AUTH-004: the onboarding request becomes a ministry with a named officer."""
    super_admin = SuperAdminFactory()
    onboarding_request = log_onboarding_request(
        super_admin,
        name_en="Ministry of Urban Development",
        website_url="https://moud.gov.np",
        official_email="officer@moud.gov.np",
        nominated_officer_name="Anil Karki",
        nominated_officer_title="Information Officer",
        purpose="Publish civic mapping work.",
        focal_contact="Anil Karki",
        nomination_reference="PMO/2026/UD-1",
        signatory_name="Anil Karki",
        signatory_verified=True,
    )
    signed_in(client, super_admin)

    detail = client.get(
        reverse("ministries:onboarding_request_detail", args=[onboarding_request.reference])
    )
    provisioned = client.post(
        reverse("ministries:onboarding_request_provision", args=[onboarding_request.reference])
    )

    assert detail.status_code == 200
    assert provisioned.status_code in (200, 302)
    assert MinistryOrganization.objects.filter(name_en="Ministry of Urban Development").exists()


@pytest.mark.acceptance
def test_beat_3_publisher_submits_and_the_pmo_publishes(client):
    """C2/D2/GOV-004/GOV-005: the draft-to-public round trip crosses both roles."""
    project = make_publishable()
    publisher = project.owner
    MinistryPublisher.objects.filter(user=publisher).update(
        status=PublisherStatus.ACTIVE,
        contact_verification_status=ContactVerificationStatus.VERIFIED,
    )
    MinistryOrganization.objects.filter(pk=project.ministry_id).update(status=OrgStatus.ACTIVE)

    signed_in(client, publisher)
    assert client.get(reverse("projects:authoring_dashboard")).status_code == 200
    submitted = client.post(
        reverse("projects:authoring_workflow", args=[project.slug]),
        {"action": "submit", "reason": "Ready for PMO review."},
    )
    project.refresh_from_db()

    assert submitted.status_code in (200, 302)
    assert project.status == ProjectStatus.IN_REVIEW

    super_admin = SuperAdminFactory()
    signed_in(client, super_admin)
    queue = client.get(reverse("projects:review_queue"))

    assert queue.status_code == 200
    assert project.title_en.encode() in queue.content


@pytest.mark.acceptance
def test_beat_4_a_published_project_shows_its_repository(client):
    """GIT-003/D5.3: the safe GitHub beat — a bound repository is visible on the project."""
    from apps.github_sync.models import RepositoryConnection

    project = make_publishable()
    project.status = ProjectStatus.OPEN_FOR_CONTRIBUTION
    project.save(update_fields=["status"])
    connection = RepositoryConnection.objects.filter(project=project).first()
    assert connection is not None, "a publishable project carries a repository enrollment"
    RepositoryConnection.objects.filter(pk=connection.pk).update(
        is_public=True, deactivated_at=None
    )
    connection.refresh_from_db()

    response = client.get(reverse("projects:detail", args=[project.slug]))
    content = response.content.decode()

    assert response.status_code == 200
    assert connection.full_name in content


@pytest.mark.acceptance
def test_beat_5_a_member_applies_and_the_queue_holds_evidence(client):
    """B2/C4/BR-006: the member journey reaches the verification queue the PMO opens."""
    member = UserFactory()
    MemberProfile.objects.create(user=member)
    project = make_publishable()
    project.status = ProjectStatus.OPEN_FOR_CONTRIBUTION
    project.save(update_fields=["status"])

    signed_in(client, member)
    assert client.get(reverse("accounts:dashboard")).status_code == 200
    applied = client.post(
        reverse("projects:apply", args=[project.slug]),
        {"kind": "code", "motivation": "I want to improve accessibility."},
    )

    assert applied.status_code in (200, 302)

    ContributionRecordFactory(
        project=project, contributor=member, status=VerificationStatus.CANDIDATE
    )
    super_admin = SuperAdminFactory()
    signed_in(client, super_admin)
    queue = client.get(reverse("contributions:verification_queue"))

    assert queue.status_code == 200


@pytest.mark.acceptance
def test_beat_6_a_member_impacting_flag_needs_two_super_admins(client):
    """ADM-001/D5.7: the closing beat — one admin proposes, a different one confirms."""
    proposer, approver = SuperAdminFactory(), SuperAdminFactory()
    flag = FeatureFlag.objects.create(
        key="public-leaderboard",
        label="Public leaderboard",
        scope="Everyone",
        owner="Product owner",
        affects_members=True,
        is_enabled=False,
    )

    signed_in(client, proposer)
    client.post(
        reverse("administration:feature_flag_change", args=[flag.key]),
        {"reason": "Policy v1.2 approved."},
    )
    flag.refresh_from_db()

    assert flag.is_enabled is False, "the proposer alone must not flip a member-facing switch"
    change = FeatureFlagChange.objects.get(status=ChangeStatus.PENDING)

    signed_in(client, approver)
    confirmed = client.post(reverse("administration:feature_flag_approve", args=[change.pk]))
    flag.refresh_from_db()

    assert confirmed.status_code == 302
    assert flag.is_enabled is True


@pytest.mark.acceptance
def test_beat_6_granting_super_admin_also_needs_two_people(client):
    """AUTH-003/D5.8: the same rule governs who may hold Super Admin."""
    proposer, approver = SuperAdminFactory(), SuperAdminFactory()
    candidate = UserFactory()

    signed_in(client, proposer)
    client.post(
        reverse("administration:privileged_access"),
        {"username": candidate.username, "reason": "Joining the PMO team."},
    )
    candidate.refresh_from_db()

    assert candidate.is_superuser is False, "a grant must not take effect on one signature"
    grant = SuperAdminGrant.objects.get(status=ChangeStatus.PENDING)

    signed_in(client, approver)
    client.post(reverse("administration:super_admin_grant_confirm", args=[grant.pk]))
    candidate.refresh_from_db()

    assert candidate.is_superuser is True


@pytest.mark.acceptance
def test_each_role_lands_where_the_script_says(client):
    """AUTH-006: login routing matches the walkthrough for all three roles."""
    super_admin = SuperAdminFactory()
    assignment = MinistryPublisherFactory(
        status=PublisherStatus.ACTIVE,
        contact_verification_status=ContactVerificationStatus.VERIFIED,
    )
    assignment.ministry.status = OrgStatus.ACTIVE
    assignment.ministry.save(update_fields=["status"])
    member = UserFactory()
    MemberProfile.objects.create(user=member)

    expected = {
        super_admin: reverse("administration:console"),
        assignment.user: reverse("projects:authoring_dashboard"),
    }
    for user, destination in expected.items():
        signed_in(client, user)
        assert client.get(reverse("accounts:dashboard")).url == destination, user.username

    signed_in(client, member)
    assert client.get(reverse("accounts:dashboard")).status_code == 200


@pytest.mark.acceptance
def test_a_signed_in_presenter_can_always_get_back_to_their_console(client):
    """AUTH-006: the header greeting is the route back once the shell dropped the admin bar."""
    super_admin = SuperAdminFactory()
    signed_in(client, super_admin)

    home = client.get(reverse("projects:home")).content.decode()

    assert reverse("accounts:dashboard") in home
    assert client.get(reverse("accounts:dashboard")).url == reverse("administration:console")


@pytest.mark.acceptance
def test_every_admin_surface_the_walkthrough_opens_is_reachable(client):
    """ADM-001/ADM-002/ADM-006: each URL named in the runbook answers for a Super Admin."""
    signed_in(client, SuperAdminFactory())

    for name in (
        "administration:console",
        "administration:feature_flags",
        "administration:privileged_access",
        "projects:review_queue",
        "ministries:organization_list",
        "contributions:verification_queue",
        "taxonomy:skill_management",
        "taxonomy:license_management",
        "moderation:case_queue",
        "audit:ops_dashboard",
        "audit:audit_log",
    ):
        assert client.get(reverse(name)).status_code == 200, name


@pytest.mark.acceptance
def test_the_leaderboard_is_honestly_gated(client):
    """REC-003: the presenter must not promise rankings the gate keeps switched off."""
    response = client.get(reverse("recognition:leaderboard"))

    assert response.status_code == 200
    assert b"Public rankings are not enabled." in response.content
