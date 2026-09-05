import pytest
from django.urls import reverse
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.audit.models import AuditEvent
from apps.projects.enums import ProjectStatus
from apps.projects.forms import ProjectCompletionForm
from apps.projects.services import (
    CompletionSummaryError,
    complete,
    save_completion_summary,
)
from apps.projects.tests.factories import ProjectFactory, make_publishable

pytestmark = pytest.mark.django_db


def verify_mfa(client, user):
    client.force_login(user)
    device = TOTPDevice.objects.get(user=user)
    device.last_t = -1
    device.save(update_fields=["last_t"])
    token = totp(
        device.bin_key,
        step=device.step,
        t0=device.t0,
        digits=device.digits,
        drift=device.drift,
    )
    response = client.post(reverse("accounts:mfa_setup"), {"token": token})
    assert response.status_code == 302


def open_project(**kwargs):
    project = make_publishable(**kwargs)
    project.status = ProjectStatus.OPEN_FOR_CONTRIBUTION
    project.save(update_fields=["status"])
    return project


@pytest.mark.unit
def test_gov009_completion_form_parses_structured_deliverables_and_rejects_unsafe_urls():
    """GOV-009/A14: completion deliverables are structured and external URLs are validated."""
    valid = ProjectCompletionForm(
        data={
            "outcome_summary": "Fourteen services now meet WCAG 2.2 AA.",
            "deliverables": "Portal v4.2 | https://example.gov.np/releases/v4.2\nAudit report",
            "impact_summary": "Completion rose from 31% to 84%.",
            "lessons_learned": "Create the Nepali accessibility glossary earlier.",
        }
    )
    invalid = ProjectCompletionForm(
        data={
            "outcome_summary": "Outcome",
            "deliverables": "Release | javascript:alert(1)",
            "impact_summary": "Impact",
            "lessons_learned": "Lessons",
        }
    )

    assert valid.is_valid(), valid.errors
    assert valid.cleaned_data["deliverables"] == [
        {"label": "Portal v4.2", "url": "https://example.gov.np/releases/v4.2"},
        {"label": "Audit report", "url": ""},
    ]
    assert not invalid.is_valid()
    assert "Use an HTTP or HTTPS URL" in invalid.errors["deliverables"][0]


@pytest.mark.unit
def test_gov009_completion_is_blocked_until_every_structured_summary_field_exists():
    """GOV-004/GOV-009/A14: a government project cannot complete with an empty summary."""
    project = open_project()
    project.outcome_summary = ""
    project.deliverables = []
    project.impact_summary = ""
    project.lessons_learned = ""
    project.save(
        update_fields=[
            "outcome_summary",
            "deliverables",
            "impact_summary",
            "lessons_learned",
        ]
    )

    with pytest.raises(CompletionSummaryError) as error:
        complete(project.owner, project)

    project.refresh_from_db()
    assert project.status == ProjectStatus.OPEN_FOR_CONTRIBUTION
    assert "outcome summary" in str(error.value)
    assert "deliverables" in str(error.value)
    assert "impact summary" in str(error.value)
    assert "lessons learned" in str(error.value)
    assert not AuditEvent.objects.filter(
        action="project.completed", object_id=str(project.pk)
    ).exists()


@pytest.mark.integration
def test_gov009_publisher_saves_summary_then_completes_with_an_audited_transition():
    """GOV-004/GOV-005/GOV-009: the publisher prepares closure data before completion."""
    project = open_project()

    save_completion_summary(
        project.owner,
        project,
        outcome_summary="Accessibility remediation shipped.",
        deliverables=[{"label": "Release v4.2", "url": "https://example.gov.np/releases/v4.2"}],
        impact_summary="Fourteen services improved.",
        lessons_learned="Test Nepali labels with assistive technology earlier.",
    )
    complete(project.owner, project)

    project.refresh_from_db()
    assert project.status == ProjectStatus.COMPLETED
    assert project.deliverables == [
        {"label": "Release v4.2", "url": "https://example.gov.np/releases/v4.2"}
    ]
    assert AuditEvent.objects.filter(
        action="project.completion_summary_updated", object_id=str(project.pk)
    ).exists()
    assert AuditEvent.objects.filter(action="project.completed", object_id=str(project.pk)).exists()


@pytest.mark.integration
def test_gov009_completion_page_saves_draft_and_can_mark_project_completed(client):
    """GOV-004/GOV-009/C5.3: the authoring UI saves and publishes a completion summary."""
    project = open_project()
    verify_mfa(client, project.owner)
    url = reverse("projects:completion_summary", kwargs={"slug": project.slug})
    payload = {
        "outcome_summary": "Fourteen services now meet WCAG 2.2 AA.",
        "deliverables": "Release v4.2 | https://example.gov.np/releases/v4.2",
        "impact_summary": "Completion rose from 31% to 84%.",
        "lessons_learned": "Create the shared glossary earlier.",
    }

    page = client.get(url)
    workflow_page = client.get(reverse("projects:authoring_detail", kwargs={"slug": project.slug}))
    saved = client.post(url, payload | {"intent": "save"})
    project.refresh_from_db()
    completed = client.post(url, payload | {"intent": "complete"})

    assert page.status_code == 200
    assert url in workflow_page.content.decode()
    assert b"Complete the project" in page.content
    assert b"published on the public listing" in page.content
    assert saved.status_code == 302
    assert project.status == ProjectStatus.OPEN_FOR_CONTRIBUTION
    assert completed.status_code == 302
    project.refresh_from_db()
    assert project.status == ProjectStatus.COMPLETED


@pytest.mark.integration
def test_gov009_completion_summary_is_public_only_after_completion(client):
    """GOV-009/DSC-009/A14: structured closure content appears on the completed listing."""
    project = ProjectFactory(
        status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
        outcome_summary="Accessibility remediation shipped.",
        deliverables=[{"label": "Release v4.2", "url": "https://example.gov.np/releases/v4.2"}],
        impact_summary="Fourteen services improved.",
        lessons_learned="Test Nepali labels earlier.",
    )
    detail_url = reverse("projects:detail", kwargs={"slug": project.slug})

    open_response = client.get(detail_url)
    project.status = ProjectStatus.COMPLETED
    project.save(update_fields=["status"])
    completed_response = client.get(detail_url)

    assert b"Accessibility remediation shipped" not in open_response.content
    assert b"Completion summary" in completed_response.content
    assert b"Accessibility remediation shipped" in completed_response.content
    assert b"Release v4.2" in completed_response.content
    assert b"Fourteen services improved" in completed_response.content
    assert b"Test Nepali labels earlier" in completed_response.content


@pytest.mark.integration
def test_gov009_legacy_completed_deliverable_labels_remain_publicly_readable(client):
    """GOV-009/A14: completed records retain compatibility with legacy string deliverables."""
    project = ProjectFactory(
        status=ProjectStatus.COMPLETED,
        outcome_summary="Legacy project completed.",
        deliverables=["Archived accessibility report"],
        impact_summary="Legacy impact record.",
        lessons_learned="Legacy lesson record.",
    )

    response = client.get(reverse("projects:detail", kwargs={"slug": project.slug}))

    assert response.status_code == 200
    assert b"Archived accessibility report" in response.content
