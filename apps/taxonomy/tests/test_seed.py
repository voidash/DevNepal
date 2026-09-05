import pytest

from apps.taxonomy.enums import TermVocabulary
from apps.taxonomy.models import ApprovedLicense, Skill, TaxonomyTerm

pytestmark = pytest.mark.integration

SEEDED_SKILLS = [
    "Python",
    "Django",
    "JavaScript",
    "React",
    "UI/UX Design",
    "Technical Writing",
    "QA/Testing",
    "Security Review",
    "Data Analysis",
    "Translation EN-NE",
    "DevOps",
    "PostgreSQL",
    "Android",
    "iOS",
    "Machine Learning",
    "Accessibility Audit",
    "Project Management",
    "Research",
    "Documentation",
    "Graphic Design",
]

GOV_008_CONTRIBUTION_TYPES = [
    "Engineering",
    "UI/UX",
    "QA",
    "Security",
    "Data",
    "Documentation",
    "Localization",
    "Research",
    "Community support",
]

SEEDED_LICENSES = [
    "MIT",
    "Apache-2.0",
    "BSD-3-Clause",
    "GPL-3.0-or-later",
    "AGPL-3.0-or-later",
    "CC-BY-4.0",
]


@pytest.mark.django_db
def test_seed_migration_creates_starter_skills():
    """MEM-004: the data migration seeds the starter skill taxonomy, all active."""
    seeded = set(Skill.objects.filter(is_active=True).values_list("name", flat=True))
    for name in SEEDED_SKILLS:
        assert name in seeded


@pytest.mark.django_db
def test_seed_migration_creates_gov008_contribution_types():
    """GOV-008: the CONTRIBUTION_TYPE vocabulary is seeded with the nine SRS categories."""
    labels = set(
        TaxonomyTerm.objects.filter(
            vocabulary=TermVocabulary.CONTRIBUTION_TYPE, is_active=True
        ).values_list("label", flat=True)
    )
    assert labels == set(GOV_008_CONTRIBUTION_TYPES)


@pytest.mark.django_db
def test_seed_migration_creates_approved_spdx_allowlist():
    """SRS 12.4/BR-003: the PMO starter SPDX allowlist is seeded, approved, and valid."""
    seeded = ApprovedLicense.objects.filter(is_approved=True)
    assert set(seeded.values_list("spdx_id", flat=True)) == set(SEEDED_LICENSES)
    for license_obj in seeded:
        license_obj.full_clean()
        assert license_obj.reference_url.startswith("https://spdx.org/licenses/")
    assert not ApprovedLicense.objects.filter(is_default=True).exists()
