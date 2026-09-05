import unicodedata

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.utils.text import slugify

from apps.projects.enums import (
    ContributionMode,
    DifficultyLevel,
    EffortBand,
    GovernanceModel,
    ProjectStatus,
    ProjectType,
    ResponseSla,
    SignoffModel,
)
from apps.projects.tests.factories import (
    MinistryOrganizationFactory,
    PersonalProjectFactory,
    ProjectFactory,
    UserFactory,
)
from apps.taxonomy.enums import DataClassification
from apps.taxonomy.tests.factories import ApprovedLicenseFactory

pytestmark = [pytest.mark.django_db]

NFD_TITLE = (
    "\u0928\u093c\u0947\u092a\u093e\u0932\u0940 "
    "\u0930\u093c\u0915\u094d\u0937\u0947\u0924\u094d\u0930"
)
NFC_TITLE = unicodedata.normalize("NFC", NFD_TITLE)


@pytest.mark.unit
def test_appendix_a_field_groups_round_trip():
    """GOV-002: the Project model captures every Appendix A field group."""
    license_obj = ApprovedLicenseFactory(spdx_id="MIT-adhoc-test", is_approved=True)
    project = ProjectFactory(
        problem_statement="No digital service directory exists",
        target_users="Citizens and developers",
        expected_outcome="A public service directory",
        success_indicators="Directory adopted by 5 ministries",
        summary_en="Open service directory",
        summary_ne="खुला सेवा निर्देशिका",
        description_md="Full description",
        background="Background notes",
        current_state="Prototype exists",
        limitations="No Nepali UI yet",
        related_initiatives="Digital Nepal framework",
        difficulty=DifficultyLevel.INTERMEDIATE,
        estimated_effort=EffortBand.MEDIUM,
        contributor_capacity=10,
        is_remote=False,
        location="Kathmandu",
        contribution_mode=ContributionMode.HYBRID,
        prerequisites="Python basics",
        communication_channel="https://matrix.to/#/#devnepal:matrix.org",
        code_of_conduct_url="https://example.com/coc",
        repository_url="https://github.com/moit/service-directory",
        default_branch="main",
        issue_tracker_url="https://github.com/moit/service-directory/issues",
        documentation_url="https://github.com/moit/service-directory#readme",
        architecture_url="https://example.com/architecture",
        environments_url="https://staging.example.com",
        test_build_instructions="uv run pytest",
        ci_status_url="https://github.com/moit/service-directory/actions",
        governance_model=GovernanceModel.LEAD_MAINTAINER,
        outcome_ownership="Ministry retains all rights",
        escalation_path="Lead maintainer, then ministry officer",
        completion_criteria="All milestones achieved and handover signed",
        license=license_obj,
        signoff_model=SignoffModel.DCO,
        third_party_rights_confirmed=True,
        content_license="CC-BY-4.0",
        security_contact="security@moit.gov.np",
        vulnerability_disclosure_url="https://moit.gov.np/security",
        prohibited_data_statement="No personal data accepted",
        dependencies="Depends on national identity API",
        risks="Staff turnover",
        outcome_summary="Directory delivered",
        deliverables=[{"label": "Portal", "url": "https://dir.gov.np"}],
        impact_summary="Improved service discovery",
        lessons_learned="Start with bilingual content",
        archive_reason="Superseded by v2",
    )
    fetched = type(project).objects.get(pk=project.pk)
    assert fetched.problem_statement == "No digital service directory exists"
    assert fetched.summary_ne == "खुला सेवा निर्देशिका"
    assert fetched.contribution_mode == ContributionMode.HYBRID
    assert fetched.estimated_effort == EffortBand.MEDIUM
    assert fetched.license == license_obj
    assert fetched.signoff_model == SignoffModel.DCO
    assert fetched.data_classification == DataClassification.PUBLIC
    assert fetched.governance_model == GovernanceModel.LEAD_MAINTAINER
    assert fetched.deliverables == [{"label": "Portal", "url": "https://dir.gov.np"}]
    assert fetched.outcome_summary == "Directory delivered"


@pytest.mark.unit
def test_devanagari_text_stored_nfc_normalized():
    """DSC-003: mixed NFC/NFD Devanagari input is composed to NFC on save."""
    assert NFD_TITLE != NFC_TITLE
    project = ProjectFactory(title_ne=NFD_TITLE, summary_ne=NFD_TITLE)
    fetched = type(project).objects.get(pk=project.pk)
    assert fetched.title_ne == NFC_TITLE
    assert fetched.summary_ne == NFC_TITLE


@pytest.mark.unit
def test_slug_unicode_unique_and_stable_on_resave():
    """DSC-003: slugs are Unicode-safe, unique, and unchanged on re-save."""
    project = ProjectFactory(
        title_en="खुला डाटा पोर्टल", slug=slugify("खुला डाटा पोर्टल", allow_unicode=True)
    )
    original_slug = project.slug
    project.title_en = "Renamed title"
    project.save(update_fields=["title_en"])
    project.refresh_from_db()
    assert project.slug == original_slug
    with pytest.raises(IntegrityError), transaction.atomic():
        ProjectFactory(slug=original_slug)


@pytest.mark.unit
def test_project_type_ministry_discriminator_constraint():
    """GOV-001/PPR-002: government projects require a ministry; personal projects forbid one."""
    with pytest.raises(IntegrityError), transaction.atomic():
        ProjectFactory(project_type=ProjectType.GOVERNMENT, ministry=None)
    with pytest.raises(IntegrityError), transaction.atomic():
        PersonalProjectFactory(
            project_type=ProjectType.PERSONAL, ministry=MinistryOrganizationFactory()
        )


@pytest.mark.unit
def test_new_project_defaults():
    """GOV-012/D5: default response expectation is one week; default class is public (9.2)."""
    project = ProjectFactory()
    assert project.status == ProjectStatus.DRAFT
    assert project.response_sla == ResponseSla.WITHIN_1_WEEK
    assert project.data_classification == DataClassification.PUBLIC
    assert project.project_type == ProjectType.GOVERNMENT
    assert project.owner is not None


@pytest.mark.unit
def test_license_reference_is_protected():
    """BR-003: an approved SPDX license referenced by a live project cannot be deleted."""
    license_obj = ApprovedLicenseFactory(is_approved=True)
    ProjectFactory(license=license_obj)
    with pytest.raises(ProtectedError):
        license_obj.delete()


@pytest.mark.unit
def test_owner_and_maintainers_are_named_users():
    """GOV-002 Identity: owner FK plus named maintainers through ProjectMaintainer."""
    from apps.projects.tests.factories import ProjectMaintainerFactory

    owner = UserFactory()
    project = ProjectFactory(owner=owner)
    lead = ProjectMaintainerFactory(project=project, role="lead", can_review_merge=True)
    assert project.owner == owner
    assert list(project.maintainers.all()) == [lead.user]
    assert lead.can_review_merge is True
