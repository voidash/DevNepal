import pytest

from apps.audit.models import AuditEvent
from apps.projects.enums import ProjectStatus
from apps.projects.services import approve, publish, request_changes, resubmit, submit_for_review
from apps.projects.tests.factories import SuperAdminFactory, make_publishable

pytestmark = [pytest.mark.django_db, pytest.mark.acceptance]


def test_a02_bilingual_draft_changes_review_and_exact_version_publication():
    """A2/GOV-004/GOV-005: publication serves the exact reviewed bilingual version."""
    project = make_publishable()
    publisher = project.owner
    super_admin = SuperAdminFactory()

    submit_for_review(publisher, project)
    request_changes(super_admin, project, reason="Clarify the Nepali public-value statement.")
    project.refresh_from_db()
    assert project.status == ProjectStatus.CHANGES_REQUESTED

    project.title_ne = "राष्ट्रिय सेवा निर्देशिका सुधार"
    project.summary_ne = "सरकारी डिजिटल सेवाहरूको सुधारिएको सार्वजनिक निर्देशिका।"
    project.save(update_fields=["title_ne", "summary_ne"])
    resubmit(publisher, project)
    approved_version = project.versions.order_by("-version_number").first()
    approve(super_admin, project)
    publish(super_admin, project)

    project.refresh_from_db()
    approved_version.refresh_from_db()
    assert project.status == ProjectStatus.OPEN_FOR_CONTRIBUTION
    assert project.current_version_id == approved_version.pk
    assert project.current_version.snapshot["title_ne"] == "राष्ट्रिय सेवा निर्देशिका सुधार"
    assert project.current_version.snapshot["summary_ne"] == project.summary_ne
    assert approved_version.published_by == super_admin
    assert AuditEvent.objects.filter(action="project.published", object_id=str(project.pk)).exists()
