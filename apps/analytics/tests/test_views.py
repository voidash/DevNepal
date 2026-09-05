from datetime import UTC, datetime

import pytest
from django.test import override_settings
from django.urls import reverse

from apps.accounts.tests.factories import UserFactory
from apps.analytics.enums import EventName
from apps.analytics.services import record_event
from apps.ministries.tests.factories import MinistryOrganizationFactory, MinistryPublisherFactory
from apps.projects.tests.factories import ProjectFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def analytics_urlconf():
    with override_settings(ROOT_URLCONF="apps.analytics.tests.urls"):
        yield


@pytest.mark.integration
def test_public_monthly_report_and_export_are_available_without_authentication(client):
    """ANL-003/ANL-004: public aggregate report and self-describing export require no account."""
    project = ProjectFactory()
    for _ in range(5):
        record_event(
            EventName.PROJECT_VIEWED,
            project=project,
            occurred_at=datetime(2026, 9, 4, tzinfo=UTC),
        )

    page = client.get(reverse("analytics:public_monthly_report"), {"month": "2026-09"})
    export = client.get(reverse("analytics:public_monthly_report_export"), {"month": "2026-09"})

    assert page.status_code == 200
    assert "Project views" in page.content.decode()
    assert export.status_code == 200
    assert export.json()["filters"] == {"month": "2026-09"}
    assert export.json()["event_counts"] == {EventName.PROJECT_VIEWED: 5}
    assert "project_counts" not in export.json()


@pytest.mark.integration
def test_ministry_dashboard_rejects_unrelated_member(client):
    """ANL-002: a member without a publisher role cannot view a ministry analytics dashboard."""
    ministry = MinistryOrganizationFactory()
    project = ProjectFactory(ministry=ministry)
    record_event(EventName.PROJECT_VIEWED, project=project)
    unrelated = UserFactory()
    client.force_login(unrelated)

    response = client.get(
        reverse("analytics:ministry_dashboard", kwargs={"ministry_id": ministry.pk})
    )

    assert response.status_code == 403


@pytest.mark.integration
@override_settings(PRIVILEGED_MFA_BYPASS=True)
def test_ministry_dashboard_shows_only_the_selected_month(client):
    """ANL-002: a verified publisher sees aggregate counts for only their ministry and month."""
    ministry = MinistryOrganizationFactory()
    publisher = MinistryPublisherFactory(ministry=ministry).user
    project = ProjectFactory(ministry=ministry)
    record_event(
        EventName.PROJECT_VIEWED,
        project=project,
        occurred_at=datetime(2026, 9, 4, tzinfo=UTC),
    )
    client.force_login(publisher)

    response = client.get(
        reverse("analytics:ministry_dashboard", kwargs={"ministry_id": ministry.pk}),
        {"month": "2026-09"},
    )

    assert response.status_code == 200
    assert response.context["aggregate"].project_counts == {project.pk: 1}
