from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.projects.enums import ProjectStatus, ResponseSla
from apps.projects.models import ProjectUpdate
from apps.projects.tests.factories import PersonalProjectFactory, ProjectUpdateFactory

pytestmark = pytest.mark.django_db


def open_listing(**kwargs):
    project = PersonalProjectFactory(status=ProjectStatus.OPEN_FOR_CONTRIBUTION, **kwargs)
    project.published_at = timezone.now() - timedelta(days=30)
    project.save(update_fields=["published_at"])
    return project


def backdate_latest_update(project, *, days: int):
    update = ProjectUpdateFactory(project=project)
    ProjectUpdate.objects.filter(pk=update.pk).update(
        created_at=timezone.now() - timedelta(days=days)
    )
    return update


@pytest.mark.integration
def test_detail_shows_last_update_age(client):
    """DSC-009: the public page shows the age of the latest maintainer update."""
    project = open_listing()
    backdate_latest_update(project, days=3)

    response = client.get(reverse("projects:detail", kwargs={"slug": project.slug}))

    assert response.status_code == 200
    assert b"Last maintainer activity" in response.content
    assert b"3 days ago" in response.content


@pytest.mark.integration
def test_detail_flags_response_overdue_once_sla_is_exceeded(client):
    """DSC-009: a live project whose latest update is older than its SLA shows the overdue state."""
    project = open_listing(response_sla=ResponseSla.WITHIN_1_WEEK)
    backdate_latest_update(project, days=8)

    response = client.get(reverse("projects:detail", kwargs={"slug": project.slug}))

    assert response.status_code == 200
    assert b"Response overdue" in response.content


@pytest.mark.integration
def test_no_overdue_state_while_updates_are_fresh(client):
    """DSC-009: a recent update keeps the project out of the overdue state."""
    project = open_listing(response_sla=ResponseSla.WITHIN_1_WEEK)
    backdate_latest_update(project, days=2)

    response = client.get(reverse("projects:detail", kwargs={"slug": project.slug}))

    assert response.status_code == 200
    assert b"Response overdue" not in response.content


@pytest.mark.integration
def test_stale_banner_after_double_sla_silence(client):
    """DSC-009: silence beyond twice the SLA raises the stale-project warning banner."""
    project = open_listing(response_sla=ResponseSla.WITHIN_1_WEEK)
    backdate_latest_update(project, days=15)

    response = client.get(reverse("projects:detail", kwargs={"slug": project.slug}))

    assert response.status_code == 200
    assert b"dn-state-banner" in response.content
    assert b"Stale project" in response.content
    assert b"Response overdue" in response.content


@pytest.mark.integration
def test_activity_indicators_hide_on_completed_listings(client):
    """DSC-009: SLA indicators only apply to live contribution states."""
    project = open_listing()
    backdate_latest_update(project, days=15)
    project.status = ProjectStatus.COMPLETED
    project.save(update_fields=["status"])

    response = client.get(reverse("projects:detail", kwargs={"slug": project.slug}))

    assert response.status_code == 200
    assert b"Response overdue" not in response.content
    assert b"Stale project" not in response.content
