import pytest

from apps.projects import enums

pytestmark = [pytest.mark.django_db]


@pytest.mark.unit
def test_project_status_is_exactly_the_nine_srs_6_1_lifecycle_states():
    """GOV-004: ProjectStatus enumerates exactly the nine SRS 6.1 lifecycle states."""
    expected = {
        "draft": "Draft",
        "in_review": "In review",
        "changes_requested": "Changes requested",
        "approved": "Approved / scheduled",
        "open_for_contribution": "Open for contribution",
        "paused": "Paused",
        "completed": "Completed",
        "cancelled": "Cancelled",
        "archived": "Archived",
    }
    assert dict(enums.ProjectStatus.choices) == expected
    assert len(enums.ProjectStatus) == 9


@pytest.mark.unit
def test_project_type_discriminates_government_and_personal():
    """GOV-002/PPR-002: the common Project record is discriminated by type."""
    assert dict(enums.ProjectType.choices) == {
        "government": "Government",
        "personal": "Personal (community)",
    }


@pytest.mark.unit
def test_contribution_mode_and_response_sla_enumerations():
    """DSC-005/GOV-007: participation mode and first-response expectation choices."""
    assert dict(enums.ContributionMode.choices) == {
        "open_direct": "Open direct contribution",
        "application": "Application required",
        "hybrid": "Hybrid (open tasks and application workstreams)",
    }
    assert dict(enums.ResponseSla.choices) == {
        "24h": "Within 24 hours",
        "3d": "Within 3 days",
        "1w": "Within 1 week",
    }


@pytest.mark.unit
def test_application_statuses_cover_dsc_007_decisions_and_withdrawal():
    """DSC-007: accept, waitlist, decline, request information plus member withdraw states."""
    assert dict(enums.ApplicationStatus.choices) == {
        "submitted": "Submitted",
        "info_requested": "Information requested",
        "waitlisted": "Waitlisted",
        "accepted": "Accepted",
        "declined": "Declined",
        "withdrawn": "Withdrawn",
    }


@pytest.mark.unit
def test_application_event_types_form_the_dsc_008_timeline_vocabulary():
    """DSC-008: application/activity timeline event vocabulary."""
    assert dict(enums.ApplicationEventType.choices) == {
        "submitted": "Submitted",
        "status_changed": "Status changed",
        "info_requested": "Information requested",
        "info_provided": "Information provided",
        "commented": "Comment",
        "assigned": "Work assigned",
        "withdrawn": "Withdrawn",
    }


@pytest.mark.unit
def test_participation_kinds_cover_interest_application_assignment():
    """DSC-005: express interest, apply, or assigned work."""
    assert dict(enums.ParticipationKind.choices) == {
        "interest": "Expressed interest",
        "application": "Application",
        "assignment": "Assigned work",
    }


@pytest.mark.unit
def test_review_decisions_record_the_gov_004_action_set():
    """GOV-004/GOV-005: review decision vocabulary including restore and approval revocation."""
    assert dict(enums.ReviewDecision.choices) == {
        "approved": "Approved",
        "changes_requested": "Changes requested",
        "rejected": "Rejected",
        "published": "Published",
        "revoked": "Approval revoked",
        "restored": "Restored from archive",
    }


@pytest.mark.unit
def test_screening_contribution_and_closure_enumerations():
    """GOV-007/GOV-008/GOV-009: task, milestone, update, and link kind vocabularies."""
    assert dict(enums.TaskStatus.choices) == {
        "open": "Open",
        "assigned": "Assigned",
        "in_progress": "In progress",
        "done": "Done",
        "cancelled": "Cancelled",
    }
    assert dict(enums.MilestoneStatus.choices) == {
        "planned": "Planned",
        "in_progress": "In progress",
        "achieved": "Achieved",
        "dropped": "Dropped",
    }
    assert dict(enums.UpdateKind.choices) == {
        "progress": "Progress",
        "milestone": "Milestone",
        "release": "Release/result",
        "completion": "Completion summary",
    }
    assert dict(enums.ProjectLinkKind.choices) == {
        "repository": "Repository",
        "demo": "Demo",
        "website": "Website",
        "documentation": "Documentation",
        "article": "Article",
        "other": "Other",
    }


@pytest.mark.unit
def test_attachment_governance_enumerations():
    """GOV-003: approved attachment kinds and malware scan statuses."""
    assert dict(enums.AttachmentKind.choices) == {
        "proposal": "Proposal",
        "requirements": "Requirements",
        "architecture": "Architecture",
        "design": "Design",
        "api_doc": "API documentation",
        "research": "Research",
        "terms": "Terms",
        "image": "Image",
        "other": "Other",
    }
    assert dict(enums.ScanStatus.choices) == {
        "pending": "Pending scan",
        "clean": "Clean",
        "quarantined": "Quarantined",
        "failed": "Scan failed",
    }


@pytest.mark.unit
def test_governance_rights_and_personal_project_enumerations():
    """GOV-002/BR-003/PPR-004: governance, signoff, maintainer roles, ownership verification."""
    assert dict(enums.GovernanceModel.choices) == {
        "maintainer_consensus": "Maintainer consensus",
        "lead_maintainer": "Lead maintainer decides",
        "ministry_approval": "Ministry approval required",
    }
    assert dict(enums.SignoffModel.choices) == {
        "dco": "DCO-style sign-off",
        "cla": "CLA required",
        "none": "None required (non-code)",
    }
    assert dict(enums.MaintainerRole.choices) == {
        "lead": "Lead maintainer",
        "maintainer": "Maintainer",
        "reviewer": "Reviewer",
    }
    assert dict(enums.OwnershipVerificationStatus.choices) == {
        "unverified": "Unverified",
        "verified_github": "Verified via GitHub",
        "verified_domain": "Verified via domain",
        "verified_manual": "Verified manually by Super Admin",
    }
    assert dict(enums.DifficultyLevel.choices) == {
        "beginner": "Beginner",
        "intermediate": "Intermediate",
        "advanced": "Advanced",
    }
    assert dict(enums.EffortBand.choices) == {
        "small": "Small (about 1 week)",
        "medium": "Medium (1-4 weeks)",
        "large": "Large (over 4 weeks)",
    }
