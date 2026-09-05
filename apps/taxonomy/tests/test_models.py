import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.taxonomy.enums import (
    ContentLanguage,
    DataClassification,
    SuggestionStatus,
    TermVocabulary,
)
from apps.taxonomy.models import SkillSuggestion
from apps.taxonomy.tests.factories import (
    ApprovedLicenseFactory,
    SkillFactory,
    SkillSuggestionFactory,
    TaxonomyTermFactory,
)

pytestmark = pytest.mark.unit


def test_content_language_enum_is_english_and_nepali_only():
    """NFR-I18N-01: shared ContentLanguage enum exposes exactly en + ne."""
    assert ContentLanguage.values == ["en", "ne"]
    assert ContentLanguage.ENGLISH == "en"
    assert ContentLanguage.NEPALI == "ne"


def test_data_classification_enum_excludes_secret_classes():
    """SEC-002/SRS 9.2: shared DataClassification carries public/internal/confidential; SECRET and
    PROHIBITED classes are never model data because the platform must not collect them."""
    assert DataClassification.values == ["public", "internal", "confidential"]
    assert not hasattr(DataClassification, "SECRET")
    assert not hasattr(DataClassification, "PROHIBITED")


@pytest.mark.django_db
def test_skill_name_is_unique():
    """MEM-004/DSC-002: duplicate skill names are rejected by the admin-managed taxonomy."""
    SkillFactory(name="Golang")
    with pytest.raises(IntegrityError), transaction.atomic():
        SkillFactory(name="Golang")


@pytest.mark.django_db
def test_skill_defaults_and_str():
    """MEM-004: new skills are active by default and render as their name."""
    skill = SkillFactory()
    assert skill.is_active is True
    assert str(skill) == skill.name


@pytest.mark.django_db
def test_term_unique_per_vocabulary_slug_and_label():
    """ADM-001/GOV-008/DSC-002: a vocabulary holds one term per slug and per label."""
    TaxonomyTermFactory(vocabulary=TermVocabulary.TECHNOLOGY, label="React", slug="react")
    with pytest.raises(IntegrityError), transaction.atomic():
        TaxonomyTermFactory(vocabulary=TermVocabulary.TECHNOLOGY, label="React", slug="react-2")
    with pytest.raises(IntegrityError), transaction.atomic():
        TaxonomyTermFactory(vocabulary=TermVocabulary.TECHNOLOGY, label="React", slug="react")


@pytest.mark.django_db
def test_term_same_slug_allowed_across_vocabularies():
    """ADM-001: identical labels/slugs may exist in different vocabularies."""
    TaxonomyTermFactory(vocabulary=TermVocabulary.TECHNOLOGY, label="Mentoring", slug="mentoring")
    term = TaxonomyTermFactory(
        vocabulary=TermVocabulary.CONTRIBUTION_TYPE, label="Mentoring", slug="mentoring"
    )
    assert term.pk is not None


@pytest.mark.django_db
def test_term_parent_is_protected_from_deletion():
    """BR-012: taxonomy edits/deletions must not silently rewrite historical meaning."""
    parent = TaxonomyTermFactory()
    TaxonomyTermFactory(parent=parent)
    with pytest.raises(ProtectedError):
        parent.delete()


@pytest.mark.django_db
def test_term_str_shows_vocabulary_and_label():
    """ADM-001: terms render as 'Vocabulary: label' for admin queues."""
    term = TaxonomyTermFactory(vocabulary=TermVocabulary.CONTRIBUTION_TYPE, label="Mentoring")
    assert str(term) == "Contribution type: Mentoring"


@pytest.mark.django_db
def test_license_accepts_spdx_identifier_syntax():
    """SRS 12.4/BR-003: SPDX identifiers (letters, digits, . + -) validate cleanly."""
    for spdx_id in (
        "MIT-Case-1",
        "Apache-2.0-x",
        "BSD3ClausePlus+",
        "GPL-3.0-only-y",
        "CC-BY-SA-4.0-z",
    ):
        ApprovedLicenseFactory.build(spdx_id=spdx_id).full_clean()


@pytest.mark.django_db
def test_license_rejects_free_text_identifiers():
    """SRS 12.4/18.3/ADM-001-U2: no free-text licenses; only SPDX identifiers are storable."""
    for spdx_id in ("MIT License", "custom/own", "GPL 3.0 or later", ""):
        license_obj = ApprovedLicenseFactory.build(spdx_id=spdx_id)
        with pytest.raises(ValidationError):
            license_obj.full_clean()


@pytest.mark.django_db
def test_license_spdx_id_is_unique():
    """ADM-001/BR-003: the allowlist holds each SPDX identifier once."""
    ApprovedLicenseFactory(spdx_id="Zlib")
    with pytest.raises(IntegrityError), transaction.atomic():
        ApprovedLicenseFactory(spdx_id="Zlib")


@pytest.mark.django_db
def test_license_str_and_defaults():
    """ADM-001/BR-003: new allowlist entries are not approved and not default until configured."""
    license_obj = ApprovedLicenseFactory(is_approved=False, is_default=False)
    assert str(license_obj) == f"{license_obj.spdx_id} ({license_obj.name})"
    assert license_obj.is_approved is False
    assert license_obj.is_default is False


@pytest.mark.django_db
def test_suggestion_defaults_to_pending():
    """MEM-004/D4: a suggestion queues as pending; only Super Admin review resolves it."""
    suggestion = SkillSuggestionFactory()
    assert suggestion.status == SuggestionStatus.PENDING
    assert suggestion.resolved_at is None
    assert suggestion.resolved_by is None
    assert str(suggestion) == f"Suggestion: {suggestion.term_name}"


@pytest.mark.django_db
def test_suggestion_term_name_unique():
    """MEM-004: only one suggestion may exist per term name."""
    SkillSuggestionFactory(term_name="Kubernetes")
    with pytest.raises(IntegrityError), transaction.atomic():
        SkillSuggestionFactory(term_name="Kubernetes")


@pytest.mark.django_db
def test_suggestion_term_name_is_case_insensitively_unique():
    """MEM-004/D4: concurrent casing variants cannot create duplicate review work."""
    SkillSuggestionFactory(term_name="Kubernetes")
    with pytest.raises(IntegrityError), transaction.atomic():
        SkillSuggestionFactory(term_name="kubernetes")


@pytest.mark.django_db
def test_suggestion_suggested_by_survives_account_deletion():
    """AUTH-010/SRS 9.3-style attribution: suggestion history survives via SET_NULL actor."""
    from django.contrib.auth import get_user_model

    member = get_user_model().objects.create_user(username="former_member")
    suggestion = SkillSuggestionFactory(term_name="Rust", suggested_by=member)
    member.delete()
    refreshed = SkillSuggestion.objects.get(pk=suggestion.pk)
    assert refreshed.suggested_by is None
    assert refreshed.term_name == "Rust"
