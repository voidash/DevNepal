import uuid

import pytest
from django.db import IntegrityError, transaction

from apps.accounts.tests.factories import attach_otp_verification
from apps.audit.models import AuditEvent
from apps.projects.enums import ProjectStatus, ReviewDecision
from apps.projects.services import (
    MaterialEditError,
    ProjectAuthorizationError,
    apply_edit,
    approve,
    publish,
    reject_submission,
    request_changes,
    submit_for_review,
)
from apps.projects.tests.factories import (
    ProjectFactory,
    ProjectReviewFactory,
    ProjectVersionFactory,
    SuperAdminFactory,
    UserFactory,
    make_publishable,
)

pytestmark = [pytest.mark.django_db]


@pytest.mark.unit
def test_version_has_uuid_pk_and_version_numbers_are_unique_per_project():
    """A2/GOV-005: versions are immutable UUID-keyed snapshots with per-project numbering."""
    project = ProjectFactory()
    first = ProjectVersionFactory(project=project, version_number=1)
    second = ProjectVersionFactory(project=project, version_number=2)
    assert isinstance(first.pk, uuid.UUID)
    assert second.version_number == 2
    with pytest.raises(IntegrityError), transaction.atomic():
        ProjectVersionFactory(project=project, version_number=2)


@pytest.mark.unit
def test_version_rows_are_immutable_except_publication_stamps():
    """A2/GOV-005: a snapshot cannot be rewritten; only publication stamps may be set later."""
    version = ProjectVersionFactory(version_number=1)
    version.published_at = version.submitted_at
    version.save()

    version.snapshot = {"tampered": True}
    with pytest.raises(PermissionError):
        version.save()

    fresh = type(version).objects.get(pk=version.pk)
    fresh.version_number = 99
    with pytest.raises(PermissionError):
        fresh.save()


@pytest.mark.unit
def test_review_records_decision_and_status_provenance():
    """GOV-005: a review row captures decision, actor, and lifecycle before/after status."""
    super_admin = SuperAdminFactory()
    project = ProjectFactory(status=ProjectStatus.IN_REVIEW)
    version = ProjectVersionFactory(project=project, version_number=1)
    review = ProjectReviewFactory(
        project=project,
        version=version,
        reviewer=super_admin,
        decision=ReviewDecision.CHANGES_REQUESTED,
        comment="Add Nepali summary",
        from_status=ProjectStatus.IN_REVIEW,
        to_status=ProjectStatus.CHANGES_REQUESTED,
    )
    fetched = type(review).objects.get(pk=review.pk)
    assert fetched.reviewer == super_admin
    assert fetched.decision == ReviewDecision.CHANGES_REQUESTED
    assert fetched.from_status == ProjectStatus.IN_REVIEW
    assert fetched.to_status == ProjectStatus.CHANGES_REQUESTED
    assert fetched.created_at is not None
    assert str(project) in str(review)


# ---------------------------------------------------------------------------
# Review workflow + material-edit services (GOV-005, GOV-006)


def submitted(project):
    submit_for_review(project.owner, project)
    project.refresh_from_db()
    return project


@pytest.mark.integration
@pytest.mark.parametrize(
    ("decision_fn", "decision", "to_status"),
    [
        (lambda sa, p: approve(sa, p), ReviewDecision.APPROVED, ProjectStatus.APPROVED),
        (
            lambda sa, p: request_changes(sa, p, reason="Clarify licensing"),
            ReviewDecision.CHANGES_REQUESTED,
            ProjectStatus.CHANGES_REQUESTED,
        ),
        (
            lambda sa, p: reject_submission(sa, p, reason="Not suitable"),
            ReviewDecision.REJECTED,
            ProjectStatus.DRAFT,
        ),
    ],
)
def test_review_actions_record_provenance(decision_fn, decision, to_status):
    """GOV-005-U1: review decisions capture actor, timestamp, comment, and versions."""
    project = submitted(make_publishable())
    super_admin = SuperAdminFactory()
    version_before = project.versions.order_by("-version_number").first()

    decision_fn(super_admin, project)
    project.refresh_from_db()

    review = project.reviews.order_by("-created_at").first()
    assert review.reviewer == super_admin
    assert review.decision == decision
    assert review.created_at is not None
    assert review.from_status == ProjectStatus.IN_REVIEW
    assert review.to_status == to_status
    assert review.version == version_before
    assert project.status == to_status


@pytest.mark.integration
def test_review_trail_mirrors_to_audit():
    """GOV-005-I1/SEC-008: every review decision is mirrored into the immutable audit log."""
    project = submitted(make_publishable())
    super_admin = SuperAdminFactory()
    approve(super_admin, project)

    audit = AuditEvent.objects.filter(action="project.approved", object_id=str(project.pk)).first()
    assert audit is not None
    assert audit.actor == super_admin
    assert audit.before["status"] == ProjectStatus.IN_REVIEW
    assert audit.after["status"] == ProjectStatus.APPROVED
    assert audit.after["version"] == str(project.versions.order_by("-version_number").first().pk)


@pytest.mark.integration
def test_approval_denied_without_otp_verified_super_admin():
    """AUTH-005/GOV-005/SEC-008: an unverified Super Admin cannot approve and denial is audited."""
    project = submitted(make_publishable())
    super_admin = SuperAdminFactory()
    super_admin.otp_device = None
    super_admin.is_verified = lambda: False

    with pytest.raises(ProjectAuthorizationError):
        approve(super_admin, project)

    project.refresh_from_db()
    assert project.status == ProjectStatus.IN_REVIEW
    assert AuditEvent.objects.filter(
        actor=super_admin, action="project.approve.denied", result="failure"
    ).exists()


@pytest.mark.integration
def test_submit_snapshots_full_field_state_into_version():
    """A2/GOV-005: submission serializes the Appendix A field state into an immutable version."""
    project = make_publishable()
    submit_for_review(project.owner, project)
    version = project.versions.get(version_number=1)
    assert version.snapshot["title_en"] == project.title_en
    assert version.snapshot["title_ne"] == project.title_ne
    assert version.snapshot["summary_ne"] == project.summary_ne
    assert version.snapshot["contribution_mode"] == project.contribution_mode
    assert version.snapshot["license"] == project.license_id
    assert version.submitted_by == project.owner


def published():
    project = submitted(make_publishable())
    super_admin = SuperAdminFactory()
    approve(super_admin, project)
    publish(super_admin, project)
    project.refresh_from_db()
    attach_otp_verification(project.owner)
    return project, super_admin


MATERIAL_CHANGES = [
    {"license_id": "new-license"},
    {"repository_url": "https://github.com/moit/other-repo"},
    {"data_classification": "internal"},
    {"description_md": "Completely new scope"},
    {"problem_statement": "New problem statement"},
    {"signoff_model": "cla"},
    {"security_contact": "security@another.gov.np"},
    {"communication_channel": "https://example.com/other-channel"},
]


@pytest.mark.integration
@pytest.mark.parametrize("changes", MATERIAL_CHANGES, ids=lambda c: sorted(c)[0])
def test_material_edits_return_published_project_to_review(changes):
    """GOV-006-U1: editing license/repository/classification/scope/agreement/contact is material."""
    from apps.taxonomy.tests.factories import ApprovedLicenseFactory

    project, _ = published()
    publisher = project.owner
    if "license_id" in changes:
        changes["license"] = ApprovedLicenseFactory(spdx_id=changes.pop("license_id"))

    versions_before = project.versions.count()
    apply_edit(publisher, project, **changes)
    project.refresh_from_db()

    assert project.status == ProjectStatus.IN_REVIEW
    assert project.versions.count() == versions_before + 1
    audit = AuditEvent.objects.filter(action="project.material_edit", object_id=str(project.pk))
    assert audit.exists()
    assert audit.first().after["status"] == ProjectStatus.IN_REVIEW


@pytest.mark.integration
def test_non_material_edit_keeps_project_published():
    """GOV-006-I1: a non-material edit to a published project does not return it to review."""
    project, _ = published()
    versions_before = project.versions.count()
    apply_edit(project.owner, project, title_en="National Service Directory v2")
    project.refresh_from_db()
    assert project.status == ProjectStatus.OPEN_FOR_CONTRIBUTION
    assert project.versions.count() == versions_before
    assert project.title_en == "National Service Directory v2"


@pytest.mark.integration
def test_material_edit_from_paused_also_returns_to_review():
    """GOV-006/D2: a material edit to a paused (still public) project re-enters review."""
    from apps.projects.services import pause

    project, _ = published()
    pause(project.owner, project)
    apply_edit(project.owner, project, data_classification="internal")
    project.refresh_from_db()
    assert project.status == ProjectStatus.IN_REVIEW


@pytest.mark.integration
def test_edit_rejects_unknown_fields_and_closed_states():
    """GOV-006: edits accept known fields only and never touch closed records."""
    from apps.projects.services import complete

    project = make_publishable()
    with pytest.raises(MaterialEditError):
        apply_edit(project.owner, project, nonexistent_field="x")

    done = published()[0]
    complete(done.owner, done)
    with pytest.raises(MaterialEditError):
        apply_edit(done.owner, done, title_en="Too late")


@pytest.mark.integration
def test_edit_requires_ministry_ownership():
    """GOV-001: a publisher of another ministry cannot edit a foreign draft."""
    from apps.ministries.tests.factories import MinistryPublisherFactory
    from apps.projects.services import ProjectAuthorizationError

    project = make_publishable()
    stranger = UserFactory()
    MinistryPublisherFactory(user=stranger)
    with pytest.raises(ProjectAuthorizationError):
        apply_edit(stranger, project, title_en="Hostile takeover")
