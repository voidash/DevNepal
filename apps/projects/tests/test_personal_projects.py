import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.projects.enums import ProjectLinkKind, ProjectStatus
from apps.projects.models import ProjectLink
from apps.projects.tests.factories import (
    ApplicationFactory,
    PersonalProjectFactory,
    ProjectFactory,
    ProjectLinkFactory,
    ProjectMaintainerFactory,
    ProjectReviewFactory,
    ProjectVersionFactory,
    UserFactory,
)

pytestmark = [pytest.mark.django_db]


@pytest.mark.unit
def test_deleting_project_with_versions_is_blocked():
    """BR-008: version history survives project deletion attempts (PROTECT)."""
    project = ProjectFactory()
    ProjectVersionFactory(project=project, version_number=1)
    with pytest.raises(ProtectedError):
        project.delete()


@pytest.mark.unit
def test_deleting_project_with_applications_is_blocked():
    """BR-008/AUTH-010: application records are retained evidence, not cascaded."""
    project = ProjectFactory()
    ApplicationFactory(project=project)
    with pytest.raises(ProtectedError):
        project.delete()


@pytest.mark.unit
def test_maintainer_assignment_unique_per_project_and_user():
    """GOV-002: a user holds at most one maintainer role per project."""
    assignment = ProjectMaintainerFactory()
    with pytest.raises(IntegrityError), transaction.atomic():
        ProjectMaintainerFactory(project=assignment.project, user=assignment.user)


@pytest.mark.unit
def test_review_history_blocks_project_deletion():
    """BR-008: review provenance survives project deletion attempts (PROTECT)."""
    project = ProjectFactory(status=ProjectStatus.IN_REVIEW)
    version = ProjectVersionFactory(project=project, version_number=1)
    ProjectReviewFactory(project=project, version=version)
    with pytest.raises(ProtectedError):
        project.delete()


@pytest.mark.unit
def test_personal_project_fields_round_trip():
    """PPR-002: personal-only role and ownership verification fields persist."""
    project = PersonalProjectFactory(role="Maintainer", ownership_verification="verified_github")
    fetched = type(project).objects.get(pk=project.pk)
    assert fetched.role == "Maintainer"
    assert fetched.ownership_verification == "verified_github"
    assert fetched.ministry_id is None


@pytest.mark.unit
def test_project_link_unique_per_project_and_url():
    """MEM-007: canonical URL variants cannot be attached twice to one project."""
    link = ProjectLinkFactory(url="https://github.com/moit/project")
    with pytest.raises(IntegrityError), transaction.atomic():
        ProjectLinkFactory(project=link.project, url="HTTPS://GitHub.COM/moit/project")
    ProjectLinkFactory(project=link.project, url="https://example.com/other")
    ProjectLinkFactory(project=ProjectFactory(owner=UserFactory()), url=link.url)


@pytest.mark.unit
def test_project_link_url_is_nfc_normalized_before_save():
    """DSC-003/MEM-007: project-link URLs are NFC-normalized before persistence."""
    link = ProjectLinkFactory(url="https://example.com/cafe\u0301")

    link.refresh_from_db()

    assert link.url == "https://example.com/caf\u00e9"


@pytest.mark.unit
@pytest.mark.parametrize(
    "unsafe_url",
    [
        "javascript:alert(1)",
        "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
        "ftp://files.example.com/payload",
    ],
)
def test_project_link_rejects_unsafe_url_schemes(unsafe_url):
    """MEM-007/SEC-004: project links accept only http and https URL schemes."""
    link = ProjectLink(
        project=ProjectFactory(),
        kind=ProjectLinkKind.WEBSITE,
        url=unsafe_url,
    )

    with pytest.raises(ValidationError) as excinfo:
        link.full_clean()

    assert "url" in excinfo.value.error_dict
