"""A4 — Discovery, application, and auditable timeline (service-level slices).

Steps 1, 2, and 4 of scenario A4 exercise public views, search, and the
notification transport, which belong to the UI-shell/notifications domains;
the steps verified here are the application flow and the timeline that this
domain owns end to end.
"""

import pytest

from apps.audit.models import AuditEvent
from apps.ministries.tests.factories import MinistryPublisherFactory
from apps.projects.enums import ApplicationStatus, ProjectStatus
from apps.projects.services import (
    apply_to_project,
    approve,
    can_view_timeline,
    decide_application,
    publish,
    submit_for_review,
)
from apps.projects.tests.factories import (
    ProjectScreeningQuestionFactory,
    SuperAdminFactory,
    UserFactory,
    make_publishable,
)

pytestmark = [pytest.mark.django_db, pytest.mark.acceptance]


@pytest.fixture
def open_bilingual_project():
    project = make_publishable()
    publisher = project.owner
    super_admin = SuperAdminFactory()
    submit_for_review(publisher, project)
    approve(super_admin, project)
    publish(super_admin, project)
    project.refresh_from_db()
    assert project.status == ProjectStatus.OPEN_FOR_CONTRIBUTION
    ProjectScreeningQuestionFactory(
        project=project, question="How many hours per week can you contribute?"
    )
    ProjectScreeningQuestionFactory(
        project=project, question="Share a link to prior work.", is_required=False
    )
    return project


def test_a04_applies_or_starts_open_task(open_bilingual_project):
    """A4 step 3 — DSC-005, DSC-006: member applies per project mode with screening answers."""
    member = UserFactory()
    required = open_bilingual_project.screening_questions.get(is_required=True)
    optional = open_bilingual_project.screening_questions.get(is_required=False)

    application = apply_to_project(
        member,
        open_bilingual_project,
        answers=[
            {"question_id": required.pk, "answer": "Eight hours"},
            {"question_id": optional.pk, "answer": "https://github.com/member/work"},
        ],
        motivation="I want to help with localization.",
    )

    assert application.status == ApplicationStatus.SUBMITTED
    assert [entry["question"] for entry in application.screening_answers] == [
        "How many hours per week can you contribute?",
        "Share a link to prior work.",
    ]

    publisher_decider = UserFactory()
    MinistryPublisherFactory(user=publisher_decider, ministry=open_bilingual_project.ministry)
    decide_application(publisher_decider, application, ApplicationStatus.ACCEPTED, note="Welcome")
    application.refresh_from_db()
    assert application.status == ApplicationStatus.ACCEPTED
    assert AuditEvent.objects.filter(
        action="application.decided", object_id=str(application.pk)
    ).exists()


def test_a04_sees_auditable_timeline(open_bilingual_project):
    """A4 step 5 — DSC-008: the timeline is complete and visible to member and ministry only."""
    member = UserFactory()
    required = open_bilingual_project.screening_questions.get(is_required=True)
    application = apply_to_project(
        member,
        open_bilingual_project,
        answers=[{"question_id": required.pk, "answer": "Five hours"}],
    )
    decider = UserFactory()
    MinistryPublisherFactory(user=decider, ministry=open_bilingual_project.ministry)
    decide_application(decider, application, ApplicationStatus.INFO_REQUESTED, note="Portfolio?")
    from apps.projects.services import provide_info

    provide_info(member, application, "Here is my portfolio.")
    decide_application(decider, application, ApplicationStatus.WAITLISTED, note="Shortlist full")

    timeline = list(application.events.order_by("created_at", "id"))
    assert [event.event for event in timeline] == [
        "submitted",
        "info_requested",
        "info_provided",
        "status_changed",
    ]
    assert all(
        timeline[i].created_at <= timeline[i + 1].created_at for i in range(len(timeline) - 1)
    )

    assert can_view_timeline(member, application) is True
    assert can_view_timeline(decider, application) is True
    assert can_view_timeline(SuperAdminFactory(), application) is True
    assert can_view_timeline(UserFactory(), application) is False
