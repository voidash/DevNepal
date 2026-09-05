import logging
from unittest import mock

import pytest
from django.urls import reverse

from apps.analytics.enums import EventName
from apps.analytics.models import AnalyticsEventRecord
from apps.analytics.services import AnalyticsEventError
from apps.projects.enums import ContributionMode, ProjectStatus
from apps.projects.models import Application
from apps.projects.services import ApplicationAnalyticsError, apply_to_project
from apps.projects.tests.factories import PersonalProjectFactory, UserFactory, make_publishable

pytestmark = pytest.mark.django_db


def open_government_project(**kwargs):
    project = make_publishable(**kwargs)
    project.status = ProjectStatus.OPEN_FOR_CONTRIBUTION
    project.save(update_fields=["status"])
    return project


@pytest.mark.integration
def test_public_government_detail_records_a_privacy_minimized_view_event(client):
    """ANL-001: a public government detail view records only the documented project event."""
    project = open_government_project()

    response = client.get(reverse("projects:detail", kwargs={"slug": project.slug}))

    event = AnalyticsEventRecord.objects.get()
    assert response.status_code == 200
    assert event.event_name == EventName.PROJECT_VIEWED
    assert event.ministry_id == project.ministry_id
    assert event.project_id == project.pk
    assert event.source_ref == ""


@pytest.mark.integration
def test_public_personal_detail_does_not_enter_the_ministry_analytics_stream(client):
    """ANL-001: personal listings do not fabricate ministry ownership in public analytics."""
    project = PersonalProjectFactory(status=ProjectStatus.OPEN_FOR_CONTRIBUTION)

    response = client.get(reverse("projects:detail", kwargs={"slug": project.slug}))

    assert response.status_code == 200
    assert not AnalyticsEventRecord.objects.exists()


@pytest.mark.integration
def test_public_detail_logs_analytics_failure_without_breaking_the_read_boundary(client, caplog):
    """ANL-001: analytics persistence failure is logged while a public project remains readable."""
    project = open_government_project()

    with (
        caplog.at_level(logging.ERROR, logger="apps.projects.views"),
        mock.patch(
            "apps.projects.views.record_event",
            side_effect=AnalyticsEventError("storage unavailable"),
        ),
    ):
        response = client.get(reverse("projects:detail", kwargs={"slug": project.slug}))

    assert response.status_code == 200
    assert "Project-view analytics recording failed" in caplog.text


@pytest.mark.integration
def test_successful_application_records_an_idempotent_project_event():
    """ANL-001: a successful government application persists one opaque-source analytics event."""
    project = open_government_project(contribution_mode=ContributionMode.APPLICATION)
    member = UserFactory()

    application = apply_to_project(member, project, motivation="Ready to help")

    event = AnalyticsEventRecord.objects.get()
    assert event.event_name == EventName.PROJECT_APPLIED
    assert event.ministry_id == project.ministry_id
    assert event.project_id == project.pk
    assert event.source_ref == f"application:{application.pk}"


@pytest.mark.integration
def test_application_rolls_back_when_analytics_persistence_fails(caplog):
    """ANL-001: application state is not committed without its required analytics event."""
    project = open_government_project(contribution_mode=ContributionMode.APPLICATION)
    member = UserFactory()

    with (
        caplog.at_level(logging.ERROR, logger="apps.projects.services"),
        mock.patch(
            "apps.projects.services.record_event",
            side_effect=AnalyticsEventError("storage unavailable"),
        ),
        pytest.raises(ApplicationAnalyticsError, match="analytics"),
    ):
        apply_to_project(member, project, motivation="Ready to help")

    assert not Application.objects.filter(project=project, applicant=member).exists()
    assert "Application analytics recording failed" in caplog.text
