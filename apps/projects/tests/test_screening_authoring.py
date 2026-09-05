import pytest
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.projects.enums import ProjectStatus
from apps.projects.models import ProjectScreeningQuestion
from apps.projects.tests.factories import (
    PersonalProjectFactory,
    ProjectScreeningQuestionFactory,
    UserFactory,
    make_publishable,
)
from apps.projects.tests.test_authoring_ui import verify_mfa

pytestmark = pytest.mark.django_db


@pytest.mark.integration
def test_publisher_adds_screening_question_through_authoring_manage(client):
    """DSC-006: an MFA-verified publisher authors screening questions for own-ministry projects."""
    project = make_publishable()
    verify_mfa(client, project.owner)
    manage_url = reverse("projects:authoring_manage", kwargs={"slug": project.slug})

    response = client.post(
        manage_url,
        {
            "action": "screening_question",
            "question": "Have you contributed to Django before?",
            "help_text": "Link your past work if possible.",
            "is_required": "on",
            "sort_order": "2",
        },
    )

    assert response.status_code == 302
    screening = ProjectScreeningQuestion.objects.get(
        project=project, question="Have you contributed to Django before?"
    )
    assert screening.is_required is True
    assert screening.sort_order == 2
    assert screening.is_active is True
    assert AuditEvent.objects.filter(
        action="project.screening_question_added", object_id=str(screening.pk)
    ).exists()


@pytest.mark.integration
def test_publisher_toggles_and_removes_screening_questions(client):
    """DSC-006: publishers retire and delete configured screening questions."""
    project = make_publishable()
    screening = ProjectScreeningQuestionFactory(project=project)
    verify_mfa(client, project.owner)
    manage_url = reverse("projects:authoring_manage", kwargs={"slug": project.slug})

    response = client.post(
        manage_url,
        {"action": "screening_toggle", "question_id": str(screening.pk), "is_active": "0"},
    )

    assert response.status_code == 302
    screening.refresh_from_db()
    assert screening.is_active is False
    assert AuditEvent.objects.filter(
        action="project.screening_question_toggled", object_id=str(screening.pk)
    ).exists()

    response = client.post(
        manage_url,
        {"action": "screening_toggle", "question_id": str(screening.pk), "is_active": "1"},
    )
    screening.refresh_from_db()
    assert screening.is_active is True

    response = client.post(
        manage_url, {"action": "screening_remove", "question_id": str(screening.pk)}
    )

    assert response.status_code == 302
    assert not ProjectScreeningQuestion.objects.filter(pk=screening.pk).exists()
    assert AuditEvent.objects.filter(
        action="project.screening_question_removed", object_id=str(project.pk)
    ).exists()


@pytest.mark.integration
def test_public_project_hides_legacy_screening_questions(client):
    """DSC-006: the issue-first public surface does not expose the retired apply form."""
    project = PersonalProjectFactory(status=ProjectStatus.OPEN_FOR_CONTRIBUTION)
    project.contribution_mode = "application"
    project.save(update_fields=["contribution_mode"])
    active = ProjectScreeningQuestionFactory(project=project, question="Active question?")
    ProjectScreeningQuestionFactory(project=project, question="Retired question?", is_active=False)
    applicant = UserFactory()
    client.force_login(applicant)

    response = client.get(reverse("projects:detail", kwargs={"slug": project.slug}))

    assert response.status_code == 200
    assert b"Active question?" not in response.content
    assert b"Retired question?" not in response.content
    assert reverse("projects:apply", kwargs={"slug": project.slug}).encode() not in response.content
    assert active.is_active is True


@pytest.mark.integration
def test_screening_authoring_is_post_only_and_ministry_scoped(client):
    """GOV-001/AUTH-006: screening actions are POST-only and hidden from foreign publishers."""
    project = make_publishable()
    screening = ProjectScreeningQuestionFactory(project=project)
    foreign_publisher_project = make_publishable()
    foreign_publisher = foreign_publisher_project.owner
    manage_url = reverse("projects:authoring_manage", kwargs={"slug": project.slug})

    verify_mfa(client, foreign_publisher)
    assert client.get(manage_url).status_code == 405

    assert (
        client.post(
            manage_url,
            {"action": "screening_toggle", "question_id": str(screening.pk), "is_active": "0"},
        ).status_code
        == 404
    )
    screening.refresh_from_db()
    assert screening.is_active is True
