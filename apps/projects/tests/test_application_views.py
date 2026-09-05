import pytest
from django.urls import reverse

from apps.projects.enums import ContributionMode, ProjectStatus
from apps.projects.models import Application
from apps.projects.tests.factories import (
    ProjectScreeningQuestionFactory,
    UserFactory,
    make_publishable,
)

pytestmark = pytest.mark.django_db


def open_project(**kwargs):
    project = make_publishable(**kwargs)
    project.status = ProjectStatus.OPEN_FOR_CONTRIBUTION
    project.save(update_fields=["status"])
    return project


@pytest.mark.integration
def test_member_submits_an_application_from_the_public_project_page(client):
    """DSC-005/DSC-006: a signed-in member submits screening answers from an open project page."""
    project = open_project(contribution_mode=ContributionMode.APPLICATION)
    question = ProjectScreeningQuestionFactory(project=project, question="Weekly availability?")
    member = UserFactory()
    client.force_login(member)

    response = client.post(
        reverse("projects:apply", kwargs={"slug": project.slug}),
        {
            "motivation": "I can maintain the Nepali localization.",
            f"answer_{question.pk}": "Ten hours",
        },
    )

    application = Application.objects.get(project=project, applicant=member)
    assert response.status_code == 302
    assert response.url == reverse("projects:detail", kwargs={"slug": project.slug})
    assert application.motivation == "I can maintain the Nepali localization."
    assert application.screening_answers == [
        {"question_id": question.pk, "question": "Weekly availability?", "answer": "Ten hours"}
    ]


@pytest.mark.integration
def test_invalid_application_is_rendered_without_creating_a_record(client):
    """DSC-005/DSC-006: missing required screening data is actionable and leaves no application."""
    project = open_project(contribution_mode=ContributionMode.APPLICATION)
    ProjectScreeningQuestionFactory(project=project, question="Weekly availability?")
    client.force_login(UserFactory())

    response = client.post(
        reverse("projects:apply", kwargs={"slug": project.slug}), {"motivation": ""}
    )

    assert response.status_code == 400
    assert b"required screening questions unanswered" in response.content
    assert not project.applications.exists()


@pytest.mark.unit
def test_anonymous_application_redirects_to_the_localized_login_page(client):
    """DSC-005: anonymous members are directed to a resolvable sign-in page before applying."""
    project = open_project(contribution_mode=ContributionMode.APPLICATION)

    response = client.post(reverse("projects:apply", kwargs={"slug": project.slug}))

    assert response.status_code == 302
    assert response.url.startswith(f"{reverse('accounts:login')}?next=")
