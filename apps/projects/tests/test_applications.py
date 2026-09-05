import unicodedata

import pytest
from django.db import IntegrityError, transaction

from apps.audit.models import AuditEvent
from apps.ministries.tests.factories import MinistryPublisherFactory
from apps.projects.enums import (
    ApplicationEventType,
    ApplicationStatus,
    ContributionMode,
    ParticipationKind,
    ProjectStatus,
)
from apps.projects.services import (
    ApplicationAuthorizationError,
    ApplicationClosedError,
    ApplicationDecisionError,
    ApplicationError,
    apply_to_project,
    can_view_timeline,
    decide_application,
    provide_info,
    withdraw_application,
)
from apps.projects.tests.factories import (
    ApplicationEventFactory,
    ApplicationFactory,
    PersonalProjectFactory,
    ProjectScreeningQuestionFactory,
    SuperAdminFactory,
    UserFactory,
    make_publishable,
)

pytestmark = [pytest.mark.django_db]


@pytest.mark.unit
def test_application_unique_per_project_applicant_kind():
    """DSC-005: one application of a given kind per member per project."""
    application = ApplicationFactory()
    with pytest.raises(IntegrityError), transaction.atomic():
        ApplicationFactory(
            project=application.project,
            applicant=application.applicant,
            kind=application.kind,
        )
    other_kind = ApplicationFactory(
        project=application.project,
        applicant=application.applicant,
        kind=ParticipationKind.INTEREST,
    )
    assert other_kind.kind == ParticipationKind.INTEREST


@pytest.mark.unit
def test_application_defaults_and_nfc_normalization():
    """DSC-005/DSC-003: applications default to submitted and store NFC-normalized text."""
    nfd = "\u0928\u093c\u0947\u092a\u093e\u0932\u0940 \u0930\u093c" + " आवेदन"
    application = ApplicationFactory(motivation=nfd)
    fetched = type(application).objects.get(pk=application.pk)
    assert fetched.status == ApplicationStatus.SUBMITTED
    assert fetched.kind == ParticipationKind.APPLICATION
    assert fetched.motivation == unicodedata.normalize("NFC", nfd)
    assert fetched.screening_answers == []
    assert fetched.decided_at is None


@pytest.mark.unit
def test_timeline_entries_are_append_only():
    """DSC-008: timeline entries can be created but never rewritten or deleted."""
    event = ApplicationEventFactory(
        event=ApplicationEventType.SUBMITTED,
        from_status="",
        to_status=ApplicationStatus.SUBMITTED,
    )
    event.comment = "rewritten"
    with pytest.raises(PermissionError):
        event.save()
    with pytest.raises(PermissionError):
        event.delete()
    created = ApplicationEventFactory(
        application=event.application,
        event=ApplicationEventType.STATUS_CHANGED,
        from_status=ApplicationStatus.SUBMITTED,
        to_status=ApplicationStatus.ACCEPTED,
    )
    assert created.pk is not None


@pytest.mark.unit
def test_application_cannot_be_created_for_personal_project_kind_default():
    """DSC-005: the participation record targets a project and snapshots nothing else by default."""
    project = PersonalProjectFactory(status=ProjectStatus.OPEN_FOR_CONTRIBUTION)
    member = UserFactory()
    application = ApplicationFactory(project=project, applicant=member)
    assert application.project == project
    assert str(application).startswith(str(member))


# ---------------------------------------------------------------------------
# Application services (DSC-005..DSC-008, BR-011)


def open_project(**kwargs):
    project = make_publishable(**kwargs)
    project.status = ProjectStatus.OPEN_FOR_CONTRIBUTION
    project.save(update_fields=["status"])
    return project


def ministry_decider(project):
    decider = UserFactory()
    MinistryPublisherFactory(user=decider, ministry=project.ministry)
    return decider


@pytest.mark.integration
def test_member_applies_to_open_project_with_screening_answers():
    """DSC-005/DSC-006: application on an open project captures configured screening answers."""
    project = open_project()
    required = ProjectScreeningQuestionFactory(project=project, question="Weekly hours?")
    optional = ProjectScreeningQuestionFactory(
        project=project, question="Portfolio URL?", is_required=False
    )
    member = UserFactory()

    application = apply_to_project(
        member,
        project,
        answers=[
            {"question_id": required.pk, "answer": "About ten hours"},
            {"question_id": optional.pk, "answer": ""},
        ],
        motivation="I can help with localization.",
    )

    assert application.status == ApplicationStatus.SUBMITTED
    assert application.project == project
    assert application.screening_answers == [
        {"question_id": required.pk, "question": "Weekly hours?", "answer": "About ten hours"},
        {"question_id": optional.pk, "question": "Portfolio URL?", "answer": ""},
    ]
    assert application.events.filter(event="submitted", actor=member).exists()


@pytest.mark.integration
def test_screening_accepts_only_project_configured_questions():
    """DSC-006-U1: unknown questions are rejected; required questions must be answered."""
    project = open_project()
    required = ProjectScreeningQuestionFactory(project=project, question="Weekly hours?")
    foreign = ProjectScreeningQuestionFactory(question="Another project's question?")
    member = UserFactory()

    with pytest.raises(ApplicationError):
        apply_to_project(
            member,
            project,
            answers=[
                {"question_id": required.pk, "answer": "ok"},
                {"question_id": foreign.pk, "answer": "x"},
            ],
        )
    with pytest.raises(ApplicationError):
        apply_to_project(member, project, answers=[{"question_id": required.pk, "answer": ""}])
    with pytest.raises(ApplicationError):
        apply_to_project(member, project, answers=[{"question_id": 999999, "answer": "x"}])
    assert not project.applications.exists()


@pytest.mark.integration
def test_mode_enforcement_direct_contribution_hides_application():
    """DSC-005-U1: direct mode rejects applications but accepts expressed interest."""
    project = open_project(contribution_mode=ContributionMode.OPEN_DIRECT)
    member = UserFactory()

    with pytest.raises(ApplicationError):
        apply_to_project(member, project)

    interest = apply_to_project(member, project, kind="interest")
    assert interest.kind == "interest"


@pytest.mark.integration
def test_duplicate_application_rejected():
    """DSC-005: a member cannot apply twice to the same project with the same kind."""
    project = open_project()
    member = UserFactory()
    apply_to_project(member, project)
    with pytest.raises(ApplicationError):
        apply_to_project(member, project)


@pytest.mark.integration
def test_application_on_draft_project_rejected():
    """DSC-005: applying to a project that is not open is refused."""
    project = make_publishable()
    with pytest.raises(ApplicationClosedError):
        apply_to_project(UserFactory(), project)


@pytest.mark.integration
@pytest.mark.parametrize("decision", ["accepted", "waitlisted", "declined", "info_requested"])
def test_decisions_use_templates_and_produce_auditable_status(decision):
    """DSC-007-I1: decisions are auditable with a reusable template note."""
    project = open_project()
    member = UserFactory()
    application = apply_to_project(member, project, motivation="Ready to help")
    decider = ministry_decider(project)

    decide_application(decider, application, decision, note="Template response")

    application.refresh_from_db()
    assert application.status == decision
    assert application.decided_by == decider
    assert application.decided_at is not None
    assert application.decision_note == "Template response"
    assert application.events.filter(
        event__in=["status_changed", "info_requested"],
        from_status=ApplicationStatus.SUBMITTED,
        to_status=decision,
    ).exists()
    assert AuditEvent.objects.filter(
        action="application.decided",
        object_id=str(application.pk),
        before__status=ApplicationStatus.SUBMITTED,
        after__status=decision,
    ).exists()


@pytest.mark.integration
def test_decision_transition_rules():
    """DSC-007: terminal decisions cannot be revisited; waitlisted can still be accepted."""
    project = open_project()
    application = apply_to_project(UserFactory(), project)
    decider = ministry_decider(project)

    decide_application(decider, application, "waitlisted")
    decide_application(decider, application, "accepted")
    application.refresh_from_db()
    assert application.status == ApplicationStatus.ACCEPTED

    with pytest.raises(ApplicationDecisionError):
        decide_application(decider, application, "declined")


@pytest.mark.integration
def test_info_request_and_provide_info_flow():
    """DSC-007/DSC-008: request-info then member response stays on the timeline."""
    project = open_project()
    member = UserFactory()
    application = apply_to_project(member, project)
    decider = ministry_decider(project)

    decide_application(decider, application, "info_requested", note="Share your portfolio")
    provide_info(member, application, "https://example.com/portfolio")
    assert application.events.filter(event="info_provided", actor=member).exists()

    decide_application(decider, application, "accepted")
    application.refresh_from_db()
    assert application.status == ApplicationStatus.ACCEPTED


@pytest.mark.integration
def test_member_can_withdraw_and_unauthorized_decider_rejected():
    """DSC-007: the applicant may withdraw; strangers cannot decide."""
    project = open_project()
    member = UserFactory()
    application = apply_to_project(member, project)

    with pytest.raises(ApplicationAuthorizationError):
        decide_application(UserFactory(), application, "accepted")

    withdraw_application(member, application)
    application.refresh_from_db()
    assert application.status == ApplicationStatus.WITHDRAWN
    assert application.events.filter(event="withdrawn", actor=member).exists()


@pytest.mark.integration
def test_timeline_visibility_member_and_ministry_only():
    """DSC-008-I1: the timeline is visible to the member and authorized ministry users only."""
    project = open_project()
    member = UserFactory()
    application = apply_to_project(member, project)
    decide_application(ministry_decider(project), application, "waitlisted")

    same_ministry = UserFactory()
    MinistryPublisherFactory(user=same_ministry, ministry=project.ministry)
    other_ministry = UserFactory()
    MinistryPublisherFactory(user=other_ministry)

    assert can_view_timeline(member, application) is True
    assert can_view_timeline(same_ministry, application) is True
    assert can_view_timeline(SuperAdminFactory(), application) is True
    assert can_view_timeline(other_ministry, application) is False
    assert can_view_timeline(UserFactory(), application) is False


@pytest.mark.integration
def test_existing_applications_stay_visible_after_project_closes():
    """BR-011: closed projects reject new applications but retain existing records and timelines."""
    project = open_project()
    member = UserFactory()
    application = apply_to_project(member, project)

    project.status = ProjectStatus.PAUSED
    project.save(update_fields=["status"])

    with pytest.raises(ApplicationClosedError):
        apply_to_project(UserFactory(), project)
    application.refresh_from_db()
    assert application.status == ApplicationStatus.SUBMITTED
    assert can_view_timeline(member, application) is True
