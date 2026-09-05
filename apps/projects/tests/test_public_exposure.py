import pytest

from apps.audit.models import AuditEvent
from apps.projects.enums import ProjectStatus, ProjectType
from apps.projects.services import (
    PublishReadinessError,
    approve,
    check_publish_readiness,
    publish,
    submit_for_review,
)
from apps.projects.tests.factories import (
    PersonalProjectFactory,
    ProjectAttachmentFactory,
    ProjectFactory,
    ProjectVersionFactory,
    SuperAdminFactory,
    make_publishable,
)

pytestmark = [pytest.mark.django_db]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("status", "versioned", "expected"),
    [
        (ProjectStatus.DRAFT, False, False),
        (ProjectStatus.IN_REVIEW, True, False),
        (ProjectStatus.CHANGES_REQUESTED, True, False),
        (ProjectStatus.APPROVED, True, True),
        (ProjectStatus.OPEN_FOR_CONTRIBUTION, True, True),
        (ProjectStatus.PAUSED, True, True),
        (ProjectStatus.COMPLETED, True, True),
        (ProjectStatus.CANCELLED, True, False),
        (ProjectStatus.ARCHIVED, True, False),
    ],
)
def test_official_badge_condition(status, versioned, expected):
    """GOV-011/BR-001: badge requires government type, live version, public status."""
    project = ProjectFactory(status=status)
    if versioned:
        ProjectVersionFactory(project=project, version_number=1)
        project.current_version = project.versions.get()
        project.save(update_fields=["current_version"])
    assert project.is_official is expected


@pytest.mark.unit
def test_official_badge_never_on_personal_projects():
    """GOV-011/BR-001: a personal project never carries the official-government badge."""
    project = PersonalProjectFactory(status=ProjectStatus.OPEN_FOR_CONTRIBUTION)
    ProjectVersionFactory(project=project, version_number=1)
    project.current_version = project.versions.get()
    project.save(update_fields=["current_version"])
    assert project.project_type == ProjectType.PERSONAL
    assert project.is_official is False


@pytest.mark.unit
def test_draft_government_project_exposes_no_official_identity():
    """BR-001: an unapproved government project has no badge or publication stamp."""
    project = ProjectFactory(status=ProjectStatus.DRAFT)
    assert project.is_official is False
    assert project.published_at is None
    assert project.current_version_id is None


# ---------------------------------------------------------------------------
# Publish-readiness gates (BR-002, BR-003, GOV-007) and publication effects


def approved():
    project = make_publishable()
    submit_for_review(project.owner, project)
    super_admin = SuperAdminFactory()
    approve(super_admin, project)
    project.refresh_from_db()
    return project, super_admin


READINESS_CASES = [
    ("maintainer_missing", lambda p: p.maintainer_assignments.all().delete()),
    ("contact_channel_missing", lambda p: setattr(p, "communication_channel", "")),
    ("contribution_mode_missing", lambda p: setattr(p, "contribution_mode", "")),
    ("response_expectation_missing", lambda p: setattr(p, "response_sla", "")),
    ("suitability_not_confirmed", lambda p: setattr(p.suitability, "confirmed_at", None)),
    ("instructions_missing", lambda p: setattr(p, "prerequisites", "")),
    ("difficulty_missing", lambda p: setattr(p, "difficulty", "")),
    ("effort_missing", lambda p: setattr(p, "estimated_effort", "")),
    ("task_missing", lambda p: p.tasks.all().delete()),
    ("license_missing", lambda p: setattr(p, "license", None)),
    ("license_not_approved", lambda p: setattr(p.license, "is_approved", False)),
    ("repository_url_missing", lambda p: setattr(p, "repository_url", "")),
    (
        "repository_connection_missing",
        lambda p: p.repository_connections.all().delete(),
    ),
    ("readme_missing", lambda p: setattr(p, "documentation_url", "")),
    ("code_of_conduct_missing", lambda p: setattr(p, "code_of_conduct_url", "")),
    ("security_path_missing", lambda p: setattr(p, "security_contact", "")),
    ("issue_entry_missing", lambda p: setattr(p, "issue_tracker_url", "")),
    ("branch_controls_missing", lambda p: setattr(p, "default_branch", "")),
    (
        "repository_readiness_unconfirmed",
        lambda p: p.suitability.checklist.update(
            repository_readiness={"checked": False, "note": ""}
        ),
    ),
]


@pytest.mark.integration
@pytest.mark.parametrize(
    ("violation", "break_it"), READINESS_CASES, ids=[c[0] for c in READINESS_CASES]
)
def test_publication_blocked_without_each_readiness_element(violation, break_it):
    """BR-002-U1/BR-003-U1/GOV-007-U1: each missing gate blocks publication."""
    project, super_admin = approved()
    break_it(project)
    project.save()
    if violation == "suitability_not_confirmed":
        project.suitability.save()
    if violation == "license_not_approved":
        project.license.save()
    if violation == "repository_readiness_unconfirmed":
        project.suitability.save()

    violations = check_publish_readiness(project)
    assert violation in violations

    with pytest.raises(PublishReadinessError) as excinfo:
        publish(super_admin, project)
    assert violation in excinfo.value.violations
    project.refresh_from_db()
    assert project.status == ProjectStatus.APPROVED


@pytest.mark.integration
def test_quarantined_attachment_blocks_publication():
    """GOV-003-I1: a failed malware scan quarantines the file and blocks publication."""
    from apps.projects.enums import ScanStatus
    from apps.projects.services import record_scan_result

    project, super_admin = approved()
    attachment = ProjectAttachmentFactory(project=project)
    record_scan_result(attachment, ScanStatus.FAILED)

    assert "attachment_quarantined" in check_publish_readiness(project)
    attachment.refresh_from_db()
    assert attachment.scan == ScanStatus.QUARANTINED
    assert not attachment.file

    with pytest.raises(PublishReadinessError):
        publish(super_admin, project)


@pytest.mark.integration
def test_publishing_serves_exactly_the_approved_version_with_badge():
    """A2/GOV-011/BR-002: publication serves exactly the approved version, badged."""
    project, super_admin = approved()
    approved_version = project.versions.order_by("-version_number").first()

    publish(super_admin, project)
    project.refresh_from_db()
    approved_version.refresh_from_db()

    assert project.status == ProjectStatus.OPEN_FOR_CONTRIBUTION
    assert project.current_version == approved_version
    assert project.published_at is not None
    assert approved_version.published_at is not None
    assert approved_version.published_by == super_admin
    assert project.is_official is True
    assert AuditEvent.objects.filter(action="project.published", object_id=str(project.pk)).exists()


@pytest.mark.integration
def test_readiness_reports_clean_only_when_complete():
    """BR-002: a fully ready project reports no violations."""
    project, _ = approved()
    assert check_publish_readiness(project) == []
