import pytest
from django.contrib import admin
from django.core.exceptions import ValidationError

from apps.taxonomy.models import ApprovedLicense, Skill, SkillSuggestion, TaxonomyTerm
from apps.taxonomy.tests.factories import ApprovedLicenseFactory

pytestmark = pytest.mark.unit


def test_all_taxonomy_models_registered_with_admin():
    """ADM-001: Super Admin manages skills/tags, project categories, approved licenses, and
    contribution types through the admin surface."""
    registry = admin.site._registry
    for model in (Skill, TaxonomyTerm, ApprovedLicense, SkillSuggestion):
        assert model in registry


def test_license_admin_exposes_allowlist_fields():
    """ADM-001/SRS 12.4: the admin license list shows SPDX identifier and approval state."""
    from apps.taxonomy.admin import ApprovedLicenseAdmin

    assert "spdx_id" in ApprovedLicenseAdmin.list_display
    assert "is_approved" in ApprovedLicenseAdmin.list_display


@pytest.mark.django_db
def test_license_entries_restricted_to_spdx_allowlist():
    """ADM-001-U2/SRS 18.3: license entries restricted to the SPDX allowlist; free text is
    not storable, so the model layer enforces the restriction for every entry path."""
    for free_text in ("MIT License", "whatever we want", "CC BY-SA"):
        entry = ApprovedLicenseFactory.build(spdx_id=free_text)
        with pytest.raises(ValidationError):
            entry.full_clean()


@pytest.mark.django_db
def test_skill_suggestions_queue_is_admin_reviewable():
    """MEM-004-I1: a missing-term suggestion becomes an admin-reviewable record with a
    status filter on the queue."""
    from apps.taxonomy.admin import SkillSuggestionAdmin

    assert "status" in SkillSuggestionAdmin.list_filter
    assert "term_name" in SkillSuggestionAdmin.list_display
