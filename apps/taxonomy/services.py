import logging
import re
import unicodedata
from functools import wraps

from django.db import IntegrityError, models, transaction
from django.utils import timezone

from apps.accounts.models import MemberSkill
from apps.accounts.permissions import is_super_admin
from apps.audit.services import record_audit
from apps.taxonomy.enums import SuggestionStatus, TaxonomyChangeAction
from apps.taxonomy.fields import normalize_nfc
from apps.taxonomy.models import ApprovedLicense, Skill, SkillSuggestion, TaxonomyVersion

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


class TaxonomyAuthorizationError(TaxonomyServiceError):
    """The actor is not a Super Admin (ADM-001)."""


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


class SkillNotPublishableError(TaxonomyServiceError):
    """A term needs both languages before it can go live (D5.5)."""


class SkillMergeError(TaxonomyServiceError):
    """A skill cannot be merged into itself or into a deprecated skill (D5.5)."""


def _require_super_admin(actor, *, action: str, obj=None) -> None:
    if is_super_admin(actor):
        return
    record_audit(
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        action=action,
        obj=obj,
        result="denied",
    )
    raise TaxonomyAuthorizationError(action)


def super_admin_required(action: str):
    """ADM-001/ADM-008: authorize before the transaction opens.

    A denial audit written inside an atomic block is rolled back by the very
    refusal it records, so the denied event never lands. Placing this decorator
    above ``transaction.atomic`` keeps the refusal outside the transaction.
    """

    def decorator(view):
        @wraps(view)
        def wrapped(actor, *args, **kwargs):
            subject = args[0] if args and hasattr(args[0], "pk") else None
            _require_super_admin(actor, action=action, obj=subject)
            return view(actor, *args, **kwargs)

        return wrapped

    return decorator


def _next_version() -> int:
    latest = TaxonomyVersion.objects.aggregate(models.Max("version"))["version__max"]
    return (latest or 0) + 1


def _record_version(actor, skill, *, action: str, diff: dict, summary: str = "") -> TaxonomyVersion:
    version = TaxonomyVersion.objects.create(
        version=_next_version(),
        action=action,
        subject=skill,
        subject_label=skill.name,
        summary=summary,
        diff=diff,
        actor=actor,
    )
    record_audit(
        actor=actor,
        action=f"taxonomy.skill_{action}",
        obj=skill,
        before=diff.get("before"),
        after=diff.get("after") | {"taxonomy_version": version.version},
    )
    return version


def skill_usage_counts() -> dict:
    """D5.5: how many members hold each skill, for the "Used by" column."""
    return {
        row["skill_id"]: row["total"]
        for row in MemberSkill.objects.values("skill_id").annotate(total=models.Count("id"))
    }


@super_admin_required("taxonomy.skill_added")
@transaction.atomic
def create_skill(actor, *, name: str, name_ne: str = "", description: str = "") -> Skill:
    """ADM-001/D5.5: add a skill, live only when both languages are present."""
    cleaned = normalize_nfc(name)
    if not cleaned:
        raise EmptySuggestionError("a skill needs a name")
    if Skill.objects.filter(name__iexact=cleaned).exists():
        raise SkillAlreadyExistsError(cleaned)
    skill = Skill.objects.create(
        name=cleaned,
        name_ne=normalize_nfc(name_ne),
        slug=slugify_unicode(cleaned),
        description=normalize_nfc(description),
        is_active=bool(cleaned and normalize_nfc(name_ne)),
    )
    _record_version(
        actor,
        skill,
        action=TaxonomyChangeAction.ADDED,
        diff={"before": None, "after": _skill_snapshot(skill)},
    )
    return skill


def _skill_snapshot(skill: Skill) -> dict:
    return {
        "name": skill.name,
        "name_ne": skill.name_ne,
        "slug": skill.slug,
        "is_active": skill.is_active,
    }


@super_admin_required("taxonomy.skill_updated")
@transaction.atomic
def update_skill(actor, skill: Skill, *, name: str, name_ne: str, description: str = "") -> Skill:
    """ADM-001/D5.5: edit a skill and record the diff under the editor's name."""
    before = _skill_snapshot(skill)
    skill.name = normalize_nfc(name) or skill.name
    skill.name_ne = normalize_nfc(name_ne)
    skill.description = normalize_nfc(description)
    if not skill.is_publishable:
        skill.is_active = False
    skill.save(update_fields=["name", "name_ne", "description", "is_active", "updated_at"])
    _record_version(
        actor,
        skill,
        action=TaxonomyChangeAction.UPDATED,
        diff={"before": before, "after": _skill_snapshot(skill)},
    )
    return skill


@super_admin_required("taxonomy.skill_state_changed")
@transaction.atomic
def set_skill_active(actor, skill: Skill, *, is_active: bool) -> Skill:
    """ADM-001/D5.5: deprecate a skill or bring it back.

    A deprecated skill disappears from pickers but existing profiles and projects
    keep it, so historic data stays readable.
    """
    action = TaxonomyChangeAction.REINSTATED if is_active else TaxonomyChangeAction.DEPRECATED
    if is_active and not skill.is_publishable:
        raise SkillNotPublishableError(skill.name)
    before = _skill_snapshot(skill)
    skill.is_active = is_active
    skill.save(update_fields=["is_active", "updated_at"])
    _record_version(
        actor, skill, action=action, diff={"before": before, "after": _skill_snapshot(skill)}
    )
    return skill


@super_admin_required("taxonomy.skill_merged")
@transaction.atomic
def merge_skills(actor, source: Skill, target: Skill) -> Skill:
    """ADM-001/D5.5: fold a duplicate skill into another, re-tagging what already uses it.

    Members and projects carrying the source skill are moved to the target, and
    the source is deprecated rather than deleted so its history survives.
    """
    if source.pk == target.pk:
        raise SkillMergeError("a skill cannot be merged into itself")
    if not target.is_active:
        raise SkillMergeError("a skill cannot be merged into a deprecated skill")

    held_by_target = set(MemberSkill.objects.filter(skill=target).values_list("user_id", flat=True))
    MemberSkill.objects.filter(skill=source, user_id__in=held_by_target).delete()
    retagged_members = MemberSkill.objects.filter(skill=source).update(skill=target)

    retagged_projects = 0
    for project in list(source.projects.all()):
        project.skills.remove(source)
        project.skills.add(target)
        retagged_projects += 1

    before = _skill_snapshot(source)
    source.is_active = False
    source.save(update_fields=["is_active", "updated_at"])
    _record_version(
        actor,
        source,
        action=TaxonomyChangeAction.MERGED,
        summary=f"Merged into {target.name}",
        diff={
            "before": before,
            "after": _skill_snapshot(source)
            | {
                "merged_into": target.slug,
                "retagged_members": retagged_members,
                "retagged_projects": retagged_projects,
            },
        },
    )
    return target


def _license_snapshot(license_record: ApprovedLicense) -> dict:
    return {
        "spdx_id": license_record.spdx_id,
        "name": license_record.name,
        "use": license_record.use,
        "legal_reference": license_record.legal_reference,
        "is_approved": license_record.is_approved,
    }


@super_admin_required("taxonomy.license_added")
@transaction.atomic
def record_license(
    actor,
    *,
    spdx_id: str,
    name: str,
    use: str,
    reference_url: str = "",
    legal_reference: str = "",
) -> ApprovedLicense:
    """ADM-001/D5.6: register a licence as pending until legal approval is recorded."""
    license_record = ApprovedLicense.objects.create(
        spdx_id=normalize_nfc(spdx_id),
        name=normalize_nfc(name),
        use=use,
        reference_url=reference_url,
        legal_reference=normalize_nfc(legal_reference),
        is_approved=False,
    )
    record_audit(
        actor=actor,
        action="taxonomy.license_added",
        obj=license_record,
        after=_license_snapshot(license_record),
    )
    return license_record


@super_admin_required("taxonomy.license_approved")
@transaction.atomic
def approve_license(actor, license_record: ApprovedLicense, *, legal_reference: str):
    """ADM-001/D5.6: record the legal approval that lets a licence be offered."""
    cleaned = normalize_nfc(legal_reference)
    if not cleaned:
        raise EmptySuggestionError("an approval needs its legal reference")
    before = _license_snapshot(license_record)
    license_record.is_approved = True
    license_record.legal_reference = cleaned
    license_record.legal_approved_on = timezone.localdate()
    license_record.save(update_fields=["is_approved", "legal_reference", "legal_approved_on"])
    record_audit(
        actor=actor,
        action="taxonomy.license_approved",
        obj=license_record,
        before=before,
        after=_license_snapshot(license_record),
    )
    return license_record


@super_admin_required("taxonomy.license_withdrawn")
@transaction.atomic
def withdraw_license(actor, license_record: ApprovedLicense, *, reason: str):
    """ADM-001/D5.6: stop offering a licence without touching already-published projects.

    The prototype is explicit that licence removals never affect projects that
    are already published, so the record is marked unapproved and kept rather
    than deleted; existing projects keep their reference to it.
    """
    cleaned = normalize_nfc(reason)
    if not cleaned:
        raise EmptySuggestionError("a withdrawal needs a reason")
    before = _license_snapshot(license_record)
    license_record.is_approved = False
    license_record.is_default = False
    license_record.save(update_fields=["is_approved", "is_default"])
    record_audit(
        actor=actor,
        action="taxonomy.license_withdrawn",
        obj=license_record,
        before=before,
        after=_license_snapshot(license_record) | {"reason": cleaned},
    )
    return license_record


def license_project_counts() -> dict:
    """D5.6: how many projects already rely on each licence."""
    from apps.projects.models import Project

    return {
        row["license_id"]: row["total"]
        for row in Project.objects.filter(license__isnull=False)
        .values("license_id")
        .annotate(total=models.Count("id"))
    }
