"""Cross-role acceptance coverage for the prototype's source-of-truth main spine."""

import pytest
from django.test import override_settings
from django.urls import reverse

from apps.accounts.models import MemberProfile
from apps.contributions.enums import ContributionSource, VerificationStatus
from apps.contributions.services import Evidence, accepted_contributions, submit_evidence, verify
from apps.contributions.tests.factories import contribution_type
from apps.ministries.tests.factories import (
    MinistryOrganizationFactory,
    MinistryPublisherFactory,
    SuperAdminFactory,
    UserFactory,
)
from apps.projects.enums import (
    ApplicationStatus,
    ContributionMode,
    MaintainerRole,
    ProjectStatus,
    TaskStatus,
    UpdateKind,
)
from apps.projects.models import SUITABILITY_AREAS
from apps.projects.services import (
    apply_edit,
    apply_to_project,
    approve,
    assign_maintainer,
    complete,
    complete_suitability,
    confirm_suitability,
    create_government_draft,
    create_task,
    decide_application,
    post_update,
    publish,
    request_changes,
    resubmit,
    save_completion_summary,
    submit_for_review,
)
from apps.recognition.models import ContributionScore
from apps.recognition.services import activate_policy
from apps.taxonomy.tests.factories import ApprovedLicenseFactory

pytestmark = [pytest.mark.django_db, pytest.mark.acceptance]


@override_settings(RECOGNITION_ENABLED=True)
def test_prototype_main_cross_role_spine(client):
    """C2/D2/A2/B2/C3/C4/C5; GOV-001/GOV-004/GOV-005/GOV-007/GOV-009/GOV-011,
    DSC-001/DSC-005/DSC-007/DSC-008, BR-002/BR-003/BR-006, and REC-001/REC-002:
    a ministry prepares and publishes a project, a member applies and submits evidence,
    a different maintainer accepts it, recognition is visible to that member, and the
    publisher records progress before completing the listing.
    """
    ministry = MinistryOrganizationFactory()
    publisher_assignment = MinistryPublisherFactory(ministry=ministry)
    publisher = publisher_assignment.user
    super_admin = SuperAdminFactory()
    non_author_maintainer = UserFactory()
    member = UserFactory()
    MemberProfile.objects.create(user=member)

    project = create_government_draft(
        publisher,
        ministry,
        title_en="Citizen Service Directory",
        title_ne="नागरिक सेवा निर्देशिका",
        summary_en="A public directory that helps residents find government services.",
        summary_ne="नागरिकलाई सरकारी सेवा खोज्न सहयोग गर्ने सार्वजनिक निर्देशिका।",
        contribution_mode=ContributionMode.APPLICATION,
        prerequisites="Familiarity with Django and accessible HTML.",
        communication_channel="https://matrix.to/#/#citizen-services:matrix.org",
        difficulty="intermediate",
        estimated_effort="medium",
        repository_url="https://github.com/moit/citizen-service-directory",
        default_branch="main",
        issue_tracker_url="https://github.com/moit/citizen-service-directory/issues",
        documentation_url="https://github.com/moit/citizen-service-directory#readme",
        code_of_conduct_url="https://example.gov.np/code-of-conduct",
        security_contact="security@example.gov.np",
        license=ApprovedLicenseFactory(is_approved=True),
    )
    assign_maintainer(
        publisher,
        project,
        user=non_author_maintainer,
        role=MaintainerRole.MAINTAINER,
        can_review_merge=True,
    )
    create_task(
        publisher,
        project,
        title="Document the first service category",
        description="Create a bilingual guide for a public service category.",
        is_starter=True,
        issue_url="https://github.com/moit/citizen-service-directory/issues/1",
        status=TaskStatus.OPEN,
    )
    complete_suitability(
        publisher,
        project,
        checklist={area: {"checked": True, "note": "Reviewed"} for area in SUITABILITY_AREAS},
        notes="The ministry has confirmed readiness for public contribution.",
    )

    submit_for_review(publisher, project)
    assert project.status == ProjectStatus.IN_REVIEW

    request_changes(
        super_admin,
        project,
        reason="Clarify the Nepali public-value statement before approval.",
    )
    assert project.status == ProjectStatus.CHANGES_REQUESTED

    apply_edit(
        publisher,
        project,
        summary_ne="नागरिकलाई सरकारी सेवा खोज्न सहयोग गर्ने सुधारिएको सार्वजनिक निर्देशिका।",
    )
    resubmit(publisher, project)
    confirm_suitability(super_admin, project)
    approve(super_admin, project)
    publish(super_admin, project)

    project.refresh_from_db()
    assert project.status == ProjectStatus.OPEN_FOR_CONTRIBUTION
    assert project.current_version is not None
    assert project.current_version.snapshot["summary_ne"] == project.summary_ne

    public_detail = client.get(reverse("projects:detail", kwargs={"slug": project.slug}))
    assert public_detail.status_code == 200
    assert project.title_en.encode() in public_detail.content

    application = apply_to_project(
        member,
        project,
        motivation="I can improve the bilingual service guidance each week.",
    )
    decide_application(
        publisher,
        application,
        ApplicationStatus.ACCEPTED,
        note="Welcome to the documentation workstream.",
    )
    application.refresh_from_db()
    assert application.status == ApplicationStatus.ACCEPTED
    assert application.events.count() == 2

    policy = activate_policy(super_admin, {"standard": 3})
    evidence = submit_evidence(
        member,
        project,
        Evidence(
            title="Bilingual service-category contribution guide",
            contribution_type=contribution_type("documentation"),
            description="Added accessible English and Nepali contributor documentation.",
            evidence_url="https://example.gov.np/evidence/service-category-guide",
        ),
    )
    assert evidence.status == VerificationStatus.CANDIDATE
    assert evidence.source == ContributionSource.MEMBER_SUBMISSION

    accepted = verify(
        non_author_maintainer,
        evidence,
        VerificationStatus.ACCEPTED,
        "The evidence is complete and the change is incorporated.",
    )
    assert accepted.verified_by == non_author_maintainer
    assert accepted.contributor == member
    credited = accepted_contributions(member).get(pk=accepted.pk)
    assert credited.contribution_type.slug == "documentation"

    score = ContributionScore.objects.get(contribution=accepted)
    assert score.policy == policy
    assert score.points == 3
    client.force_login(member)
    recognition = client.get(reverse("recognition:my_profile"))
    assert recognition.status_code == 200
    assert list(recognition.context["scores"]) == [score]

    update = post_update(
        publisher,
        project,
        title="First contribution accepted",
        body="The first bilingual documentation contribution has been reviewed and accepted.",
        kind=UpdateKind.PROGRESS,
        link="https://github.com/moit/citizen-service-directory/releases/tag/v0.1",
    )
    save_completion_summary(
        publisher,
        project,
        outcome_summary="The bilingual service directory shipped for public use.",
        deliverables=[
            {
                "label": "Citizen Service Directory v0.1",
                "url": "https://github.com/moit/citizen-service-directory/releases/tag/v0.1",
            }
        ],
        impact_summary="Residents can find service guidance in English and Nepali.",
        lessons_learned="Accessible bilingual guidance should be tested from the first release.",
    )
    complete(publisher, project)

    project.refresh_from_db()
    assert update.created_by == publisher
    assert project.status == ProjectStatus.COMPLETED
