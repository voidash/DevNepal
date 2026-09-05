import logging
import re
import unicodedata

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.services import record_audit
from apps.taxonomy.enums import SuggestionStatus
from apps.taxonomy.fields import normalize_nfc
from apps.taxonomy.models import Skill, SkillSuggestion

logger = logging.getLogger(__name__)

_COMBINING_CATEGORIES = {"Mn", "Mc"}
_DISALLOWED = re.compile(r"[^\w\s-]", re.UNICODE)


def slugify_unicode(value: str) -> str:
    """Unicode slug that keeps Devanagari matras/virama (DSC-003).

    Django's slugify drops combining marks even with allow_unicode, which mangles
    Devanagari text; this variant preserves them.
    """
    normalized = normalize_nfc(value).lower()
    kept = "".join(
        char
        if not _DISALLOWED.match(char) or unicodedata.category(char) in _COMBINING_CATEGORIES
        else ""
        for char in normalized
    )
    return "-".join(part for part in kept.split() if part)


class TaxonomyServiceError(Exception):
    """Base class for taxonomy service failures."""


class EmptySuggestionError(TaxonomyServiceError):
    """A skill suggestion must carry a non-blank term name (MEM-004)."""


class DuplicateSuggestionError(TaxonomyServiceError):
    """Only one suggestion may exist per term name (MEM-004)."""


class ExistingSkillError(TaxonomyServiceError):
    """Suggestions exist for missing terms only; the term is already in the taxonomy (MEM-004)."""


class SkillAlreadyExistsError(TaxonomyServiceError):
    """Approval must promote, never overwrite: the term already exists as a Skill (D4)."""


class SuggestionAlreadyResolvedError(TaxonomyServiceError):
    """A suggestion is reviewed exactly once (D4)."""


def suggest_skill(member, term, note="") -> SkillSuggestion:
    """Queue a member's missing-term suggestion for Super Admin review (MEM-004, D4)."""
    normalized_term = normalize_nfc(term or "")
    if not normalized_term:
        raise EmptySuggestionError("Suggested skill term is empty.")
    if Skill.objects.filter(name__iexact=normalized_term).exists():
        raise ExistingSkillError(f"Skill '{normalized_term}' already exists in the taxonomy.")
    if SkillSuggestion.objects.filter(term_name__iexact=normalized_term).exists():
        raise DuplicateSuggestionError(f"A suggestion for '{normalized_term}' already exists.")
    try:
        with transaction.atomic():
            suggestion = SkillSuggestion.objects.create(
                suggested_by=member,
                term_name=normalized_term,
                note=normalize_nfc(note or ""),
            )
            record_audit(
                actor=member,
                action="taxonomy.skill_suggestion.submitted",
                obj=suggestion,
                after={"status": suggestion.status},
            )
            return suggestion
    except IntegrityError:
        logger.exception("Concurrent skill suggestion for term %r rejected", normalized_term)
        raise DuplicateSuggestionError(
            f"A suggestion for '{normalized_term}' already exists."
        ) from None


def review_suggestion(super_admin, suggestion, approve: bool) -> SkillSuggestion:
    """Resolve a pending suggestion; approval promotes it to a Skill (MEM-004, D4, ADM-001).

    Role enforcement (Super Admin) happens at the calling boundary via the accounts
    role model; every resolution is audited regardless of caller.
    """
    if suggestion.status != SuggestionStatus.PENDING:
        raise SuggestionAlreadyResolvedError(
            f"Suggestion '{suggestion.term_name}' was already resolved as {suggestion.status}."
        )
    before = {"status": suggestion.status}
    if not approve:
        with transaction.atomic():
            suggestion.status = SuggestionStatus.DISMISSED
            suggestion.resolved_by = super_admin
            suggestion.resolved_at = timezone.now()
            suggestion.save(update_fields=["status", "resolved_by", "resolved_at"])
            record_audit(
                actor=super_admin,
                action="taxonomy.skill_suggestion.dismissed",
                obj=suggestion,
                before=before,
                after={"status": suggestion.status},
            )
        return suggestion

    if Skill.objects.filter(name__iexact=suggestion.term_name).exists():
        raise SkillAlreadyExistsError(
            f"Skill '{suggestion.term_name}' already exists; approval cannot overwrite it."
        )
    slug = slugify_unicode(suggestion.term_name)
    if Skill.objects.filter(slug=slug).exists():
        raise SkillAlreadyExistsError(f"Slug '{slug}' is already used by another skill.")
    try:
        with transaction.atomic():
            skill = Skill.objects.create(name=suggestion.term_name, slug=slug)
            suggestion.status = SuggestionStatus.ACCEPTED
            suggestion.resolved_by = super_admin
            suggestion.resolved_at = timezone.now()
            suggestion.save(update_fields=["status", "resolved_by", "resolved_at"])
            record_audit(
                actor=super_admin,
                action="taxonomy.skill_suggestion.approved",
                obj=suggestion,
                before=before,
                after={"status": suggestion.status, "skill_id": skill.pk},
            )
    except IntegrityError:
        logger.exception(
            "Promotion of suggestion %r to Skill failed on uniqueness", suggestion.term_name
        )
        raise SkillAlreadyExistsError(
            f"Skill '{suggestion.term_name}' already exists; approval cannot overwrite it."
        ) from None
    return suggestion
