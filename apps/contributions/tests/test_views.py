import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.audit.models import AuditEvent
from apps.contributions.enums import ContributionSource, VerificationStatus
from apps.contributions.models import ContributionRecord
from apps.contributions.services import place_on_hold
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


@pytest.fixture(autouse=True)
def isolated_evidence_storage(settings, tmp_path):
    """SEC-007: view tests never persist uploads outside their temporary directory."""
    settings.MEDIA_ROOT = tmp_path


def verify_mfa(client, user):
    """Create an OTP-verified session rather than bypassing the PMO authorization boundary."""
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
def test_member_submits_content_checked_file_evidence_through_the_authenticated_form(client):
    """SEC-007/A6: the submission route passes a validated evidence upload to the service layer."""
    member = UserFactory()
    project = ProjectFactory(
        status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
        contribution_mode=ContributionMode.OPEN_DIRECT,
    )
    client.force_login(member)

    response = client.post(
        reverse("contributions:submit", kwargs={"project_id": project.pk}),
        {
            "title": "Accessibility evidence",
            "contribution_type": contribution_type("qa").pk,
            "evidence_file": SimpleUploadedFile("review.pdf", b"%PDF-1.7 evidence"),
        },
    )

    record = ContributionRecord.objects.get()
    assert response.status_code == 302
    assert record.evidence_content_type == "application/pdf"
    assert record.evidence_size_bytes == len(b"%PDF-1.7 evidence")


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
def test_open_direct_project_does_not_link_the_retired_evidence_submission_flow(client):
    """A5/B2.5/DSC-005: the public page keeps contribution on GitHub."""
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
    assert submit_url not in response.content.decode()
    assert "Submit evidence" not in response.content.decode()


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
def test_verification_queue_exposes_provenance_review_age_sla_and_escalation(client):
    """REC-006/C4.1/C4.2: reviewers see source, checks, age, SLA, and escalation."""
    owned = ContributionRecordFactory(
        source=ContributionSource.PROVIDER_EVENT,
        provider_event_ref="github:queue-check-1",
        project__response_sla="3d",
        project__escalation_path="Escalate to the PMO duty officer after the published SLA.",
    )
    maintainer = ProjectMaintainerFactory(project=owned.project).user
    client.force_login(maintainer)

    response = client.get(reverse("contributions:verification_queue"))
    content = response.content.decode()

    assert response.status_code == 200
    assert owned.get_source_display() in content
    assert "Automated check" in content
    assert "provider event reference recorded" in content
    assert "Age" in content
    assert "Review SLA" in content
    assert "Within 3 days" in content
    assert owned.project.escalation_path in content


@pytest.mark.unit
def test_verified_pmo_can_hold_and_release_a_candidate_from_the_detail_screen(client):
    """D4.1/D4.3/AUTH-005: PMO hold routes preserve the candidate and its history."""
    record = ContributionRecordFactory()
    pmo = SuperAdminFactory()
    verify_mfa(client, pmo)

    held = client.post(
        reverse("contributions:hold", kwargs={"contribution_id": record.pk}),
        {"reason": "Rate-cap anomaly is awaiting review."},
    )
    record.refresh_from_db()
    assert held.status_code == 302
    assert record.status == VerificationStatus.CANDIDATE
    assert record.hold_active is True

    released = client.post(
        reverse("contributions:release_hold", kwargs={"contribution_id": record.pk}),
        {"reason": "The review found no duplicate work."},
    )
    record.refresh_from_db()
    assert released.status_code == 302
    assert record.status == VerificationStatus.CANDIDATE
    assert record.hold_active is False


@pytest.mark.unit
def test_non_pmo_cannot_place_a_contribution_on_hold(client):
    """D4.1/AUTH-005: only an OTP-verified Super Admin can hold an outcome."""
    record = ContributionRecordFactory()
    client.force_login(UserFactory())

    response = client.post(
        reverse("contributions:hold", kwargs={"contribution_id": record.pk}),
        {"reason": "Forged hold"},
    )

    record.refresh_from_db()
    assert response.status_code == 403
    assert record.status == VerificationStatus.CANDIDATE


@pytest.mark.unit
def test_only_affected_contributor_can_submit_one_pmo_hold_response(client):
    """D4.2/REC-006: the affected member posts one response that PMO can inspect."""
    record = ContributionRecordFactory()
    pmo = SuperAdminFactory()
    place_on_hold(pmo, record, "Please explain the rapid activity.")
    client.force_login(record.contributor)

    response = client.post(
        reverse("contributions:hold_response", kwargs={"contribution_id": record.pk}),
        {"response": "Each contribution addresses a separate documented issue."},
    )
    record.refresh_from_db()

    assert response.status_code == 302
    assert record.hold_response == "Each contribution addresses a separate documented issue."

    verify_mfa(client, pmo)
    pmo_detail = client.get(reverse("contributions:detail", kwargs={"contribution_id": record.pk}))
    assert pmo_detail.status_code == 200
    assert record.hold_response in pmo_detail.content.decode()

    client.force_login(UserFactory())
    denied = client.post(
        reverse("contributions:hold_response", kwargs={"contribution_id": record.pk}),
        {"response": "Forged follow-up"},
    )
    assert denied.status_code == 403


@pytest.mark.unit
def test_unrelated_member_cannot_open_verification_queue(client):
    """C4.1/AUTH-006: the review queue is unavailable to members without project authority."""
    client.force_login(UserFactory())

    response = client.get(reverse("contributions:verification_queue"))

    assert response.status_code == 403
