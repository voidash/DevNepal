import pytest
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.contributions.enums import VerificationStatus
from apps.contributions.models import ContributionRecord
from apps.contributions.tests.factories import ContributionRecordFactory, contribution_type
from apps.ministries.tests.factories import SuperAdminFactory, UserFactory
from apps.projects.enums import ApplicationStatus, ContributionMode, ProjectStatus
from apps.projects.tests.factories import (
    ApplicationFactory,
    ProjectFactory,
    ProjectMaintainerFactory,
    ProjectVersionFactory,
)

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.contributions.tests.urls"),
]


@pytest.mark.unit
def test_member_submits_non_code_evidence_through_the_authenticated_form(client):
    """A6/BR-006: a member submits non-code evidence as an unverified candidate."""
    member = UserFactory()
    project = ProjectFactory(
        status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
        contribution_mode=ContributionMode.OPEN_DIRECT,
    )
    client.force_login(member)

    response = client.post(
        reverse("contributions:submit", kwargs={"project_id": project.pk}),
        {
            "title": "Accessibility audit",
            "contribution_type": contribution_type("qa").pk,
            "description": "Tested keyboard navigation.",
            "evidence_url": "https://example.com/audit",
        },
    )

    record = ContributionRecord.objects.get()
    assert response.status_code == 302
    assert response.url == reverse("contributions:detail", kwargs={"contribution_id": record.pk})
    assert record.contributor == member
    assert record.status == VerificationStatus.CANDIDATE
    assert record.contribution_type.slug == "qa"


@pytest.mark.unit
def test_contribution_detail_and_history_are_scoped_to_contributor_or_authorized_reviewer(client):
    """AUTH-006/DSC-008: evidence and its history do not leak to unrelated members."""
    record = ContributionRecordFactory()
    maintainer = ProjectMaintainerFactory(project=record.project).user
    client.force_login(UserFactory())

    detail_url = reverse("contributions:detail", kwargs={"contribution_id": record.pk})
    history_url = reverse("contributions:history", kwargs={"contribution_id": record.pk})
    assert client.get(detail_url).status_code == 404
    assert client.get(history_url).status_code == 404

    client.force_login(record.contributor)
    assert client.get(detail_url).status_code == 200

    client.force_login(maintainer)
    assert client.get(history_url).status_code == 200


@pytest.mark.unit
def test_forged_reviewer_is_denied_and_the_service_audits_the_attempt(client):
    """BR-006/AUTH-006/SEC-008: a member cannot forge verification authority through the route."""
    record = ContributionRecordFactory()
    attacker = UserFactory()
    client.force_login(attacker)

    response = client.post(
        reverse("contributions:verify", kwargs={"contribution_id": record.pk}),
        {"decision": VerificationStatus.ACCEPTED, "reason": "Forged approval"},
    )

    record.refresh_from_db()
    assert response.status_code == 403
    assert record.status == VerificationStatus.CANDIDATE
    assert AuditEvent.objects.filter(
        actor=attacker,
        action="contribution.verify.denied",
        object_id=str(record.pk),
        result="failure",
    ).exists()


@pytest.mark.unit
def test_authorized_maintainer_verifies_and_super_admin_revocation_requires_mfa(client):
    """A5/A6/AUTH-005/REC-005: verification is authorized and privileged revocation needs MFA."""
    record = ContributionRecordFactory()
    maintainer = ProjectMaintainerFactory(project=record.project).user
    client.force_login(maintainer)

    verified = client.post(
        reverse("contributions:verify", kwargs={"contribution_id": record.pk}),
        {"decision": VerificationStatus.ACCEPTED, "reason": "Reviewed and accepted"},
    )
    record.refresh_from_db()
    assert verified.status_code == 302
    assert record.status == VerificationStatus.ACCEPTED

    super_admin = SuperAdminFactory()
    super_admin.is_verified = lambda: False
    client.force_login(super_admin)
    denied = client.post(
        reverse("contributions:revoke", kwargs={"contribution_id": record.pk}),
        {"reason": "Attempted without MFA"},
    )
    record.refresh_from_db()
    assert denied.status_code == 403
    assert record.status == VerificationStatus.ACCEPTED


@pytest.mark.unit
def test_mutating_contribution_routes_reject_missing_csrf_tokens():
    """SEC-004: evidence, verification, and revocation routes retain Django CSRF protection."""
    from django.test import Client

    client = Client(enforce_csrf_checks=True)
    member = UserFactory()
    project = ProjectFactory()
    client.force_login(member)

    response = client.post(reverse("contributions:submit", kwargs={"project_id": project.pk}), {})

    assert response.status_code == 403


@pytest.mark.unit
@pytest.mark.parametrize(
    ("status", "mode"),
    (
        (ProjectStatus.DRAFT, ContributionMode.OPEN_DIRECT),
        (ProjectStatus.PAUSED, ContributionMode.OPEN_DIRECT),
        (ProjectStatus.OPEN_FOR_CONTRIBUTION, ContributionMode.APPLICATION),
    ),
)
def test_hidden_evidence_submission_urls_reject_ineligible_project_states(client, status, mode):
    """DSC-005/BR-006: hidden URLs cannot submit evidence to ineligible work."""
    member = UserFactory()
    project = ProjectFactory(status=status, contribution_mode=mode)
    client.force_login(member)
    submit_url = reverse("contributions:submit", kwargs={"project_id": project.pk})

    assert client.get(submit_url).status_code == 404
    assert (
        client.post(
            submit_url,
            {
                "title": "Hidden-route evidence",
                "contribution_type": contribution_type("qa").pk,
                "description": "This must not create a candidate.",
            },
        ).status_code
        == 404
    )
    assert not ContributionRecord.objects.filter(project=project).exists()


@pytest.mark.unit
def test_open_direct_project_links_authenticated_member_to_evidence_submission(client):
    """A5/B2.5/DSC-005: an eligible public project exposes a member evidence-submission entry."""
    member = UserFactory()
    project = ProjectFactory(
        status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
        contribution_mode=ContributionMode.OPEN_DIRECT,
    )
    version = ProjectVersionFactory(project=project)
    project.current_version = version
    project.save(update_fields=["current_version"])
    client.force_login(member)

    response = client.get(reverse("projects:detail", kwargs={"slug": project.slug}))

    assert response.status_code == 200
    submit_url = reverse("contributions:submit", kwargs={"project_id": project.pk})
    assert submit_url in response.content.decode()
    assert "Submit evidence" in response.content.decode()


@pytest.mark.unit
def test_accepted_application_unlocks_evidence_submission_for_that_member(client):
    """B2.4/B2.5/DSC-005: accepted applicants can submit evidence through their application."""
    member = UserFactory()
    project = ProjectFactory(
        status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
        contribution_mode=ContributionMode.APPLICATION,
    )
    application = ApplicationFactory(
        project=project,
        applicant=member,
        status=ApplicationStatus.ACCEPTED,
    )
    client.force_login(member)
    submit_url = reverse("contributions:submit", kwargs={"project_id": project.pk})

    submit_response = client.get(submit_url)
    application_response = client.get(
        reverse("projects:application_detail", kwargs={"application_id": application.pk})
    )

    assert submit_response.status_code == 200
    assert application_response.status_code == 200
    assert submit_url in application_response.content.decode()
    assert "Submit evidence" in application_response.content.decode()


@pytest.mark.unit
def test_maintainer_verification_queue_scopes_candidates_to_owned_projects(client):
    """C4.1/BR-006/AUTH-006: maintainers can discover only candidates for projects they review."""
    owned = ContributionRecordFactory(status=VerificationStatus.CANDIDATE)
    maintainer = ProjectMaintainerFactory(project=owned.project).user
    other = ContributionRecordFactory(status=VerificationStatus.CANDIDATE)
    client.force_login(maintainer)

    response = client.get(reverse("contributions:verification_queue"))

    content = response.content.decode()
    assert response.status_code == 200
    assert list(response.context["contributions"]) == [owned]
    assert owned.title in content
    assert other.title not in content
    assert reverse("contributions:detail", kwargs={"contribution_id": owned.pk}) in content


@pytest.mark.unit
def test_unrelated_member_cannot_open_verification_queue(client):
    """C4.1/AUTH-006: the review queue is unavailable to members without project authority."""
    client.force_login(UserFactory())

    response = client.get(reverse("contributions:verification_queue"))

    assert response.status_code == 403
