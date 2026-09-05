import unicodedata

import pytest
from django.contrib.auth import get_user_model

from apps.audit.models import AuditEvent
from apps.taxonomy.enums import SuggestionStatus
from apps.taxonomy.models import Skill
from apps.taxonomy.services import (
    DuplicateSuggestionError,
    EmptySuggestionError,
    ExistingSkillError,
    SkillAlreadyExistsError,
    SuggestionAlreadyResolvedError,
    review_suggestion,
    suggest_skill,
)
from apps.taxonomy.tests.factories import SkillFactory

pytestmark = pytest.mark.integration


@pytest.fixture
def member(db):
    return get_user_model().objects.create_user(username="contributor")


@pytest.fixture
def super_admin(db):
    return get_user_model().objects.create_user(username="superadmin")


@pytest.mark.django_db
def test_suggest_skill_creates_pending_suggestion(member):
    """MEM-004: a missing-term suggestion becomes an admin-reviewable pending record."""
    suggestion = suggest_skill(member, "Kubernetes")
    assert suggestion.status == SuggestionStatus.PENDING
    assert suggestion.suggested_by == member
    assert suggestion.term_name == "Kubernetes"


@pytest.mark.django_db
def test_suggest_skill_normalizes_term_nfc(member):
    """DSC-003/MEM-004: suggested terms are NFC-normalized before queueing."""
    nfd = unicodedata.normalize("NFD", "डाटा विश्लेषण")
    suggestion = suggest_skill(member, f"  {nfd} ")
    assert suggestion.term_name == "डाटा विश्लेषण"


@pytest.mark.django_db
def test_suggest_skill_rejects_blank_term(member):
    """MEM-004: empty suggestions cannot enter the queue."""
    with pytest.raises(EmptySuggestionError):
        suggest_skill(member, "   ")


@pytest.mark.django_db
def test_suggest_skill_rejects_duplicate_pending_term(member):
    """MEM-004: one suggestion per term name; duplicates are refused with a typed error."""
    suggest_skill(member, "Kubernetes")
    with pytest.raises(DuplicateSuggestionError):
        suggest_skill(member, "Kubernetes")


@pytest.mark.django_db
def test_suggest_skill_rejects_existing_skill_term(member):
    """MEM-004: suggestions are for missing terms only; existing taxonomy skills are refused."""
    SkillFactory(name="Golang")
    with pytest.raises(ExistingSkillError):
        suggest_skill(member, "Golang")


@pytest.mark.django_db
def test_review_suggestion_approval_promotes_to_skill_and_audits(member, super_admin):
    """D4/ADM-001: Super Admin approval promotes a suggestion to a Skill and writes audit."""
    suggestion = suggest_skill(member, "Kubernetes")
    review_suggestion(super_admin, suggestion, approve=True)
    suggestion.refresh_from_db()
    skill = Skill.objects.get(name="Kubernetes")
    assert suggestion.status == SuggestionStatus.ACCEPTED
    assert suggestion.resolved_by == super_admin
    assert suggestion.resolved_at is not None
    assert skill.slug == "kubernetes"
    event = AuditEvent.objects.get(
        action="taxonomy.skill_suggestion.approved", object_id=str(suggestion.pk)
    )
    assert event.actor == super_admin
    assert event.before == {"status": SuggestionStatus.PENDING}
    assert event.after["status"] == SuggestionStatus.ACCEPTED
    assert event.after["skill_id"] == skill.pk


@pytest.mark.django_db
def test_review_suggestion_dismissal_audits_without_creating_skill(member, super_admin):
    """D4/ADM-001: Super Admin dismissal resolves the suggestion with audit and no Skill."""
    suggestion = suggest_skill(member, "Kubernetes")
    review_suggestion(super_admin, suggestion, approve=False)
    suggestion.refresh_from_db()
    assert suggestion.status == SuggestionStatus.DISMISSED
    assert suggestion.resolved_by == super_admin
    assert not Skill.objects.filter(name="Kubernetes").exists()
    event = AuditEvent.objects.get(
        action="taxonomy.skill_suggestion.dismissed", object_id=str(suggestion.pk)
    )
    assert event.actor == super_admin
    assert event.after == {"status": SuggestionStatus.DISMISSED}


@pytest.mark.django_db
def test_review_suggestion_refuses_double_review(member, super_admin):
    """ADM-001: a suggestion is reviewed exactly once; re-review fails closed."""
    suggestion = suggest_skill(member, "Kubernetes")
    review_suggestion(super_admin, suggestion, approve=True)
    with pytest.raises(SuggestionAlreadyResolvedError):
        review_suggestion(super_admin, suggestion, approve=False)


@pytest.mark.django_db
def test_review_suggestion_approval_refuses_existing_skill_name(member, super_admin):
    """D4/MEM-004: approval never overwrites an existing skill; suggestion stays pending."""
    suggestion = suggest_skill(member, "Kubernetes")
    SkillFactory(name="Kubernetes", slug="kubernetes")
    with pytest.raises(SkillAlreadyExistsError):
        review_suggestion(super_admin, suggestion, approve=True)
    suggestion.refresh_from_db()
    assert suggestion.status == SuggestionStatus.PENDING
    assert not AuditEvent.objects.filter(action="taxonomy.skill_suggestion.approved").exists()


@pytest.mark.django_db
def test_approved_suggestion_promotes_devanagari_term(member, super_admin):
    """MEM-004/DSC-003: a Devanagari term promotes into a Skill with a unicode slug."""
    suggestion = suggest_skill(member, "नेपाली अनुवाद")
    review_suggestion(super_admin, suggestion, approve=True)
    skill = Skill.objects.get(name="नेपाली अनुवाद")
    assert skill.slug == unicodedata.normalize("NFC", "नेपाली-अनुवाद")
