import typing

from django.core.validators import RegexValidator
from django.db import models
from django.utils.translation import get_language

from apps.taxonomy.enums import (
    LicenseUse,
    SuggestionStatus,
    TaxonomyChangeAction,
    TermVocabulary,
)
from apps.taxonomy.fields import NFCCharField, NFCSlugField, NFCTextField


class Skill(models.Model):
    name = NFCCharField(100)
    name_ne = NFCCharField(100, blank=True, default="")
    slug = NFCSlugField(120, allow_unicode=True, unique=True)
    description = NFCTextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["name"]
        constraints: typing.ClassVar[list] = [
            models.UniqueConstraint(fields=["name"], name="uniq_skill_name"),
        ]
        indexes: typing.ClassVar[list] = [
            models.Index(fields=["is_active"], name="idx_skill_active"),
        ]

    def __str__(self):
        return self.name

    @property
    def localized_name(self) -> str:
        if get_language() == "ne" and self.name_ne:
            return self.name_ne
        return self.name

    @property
    def is_publishable(self) -> bool:
        """DSC-001/D5.5: a term goes live only when both languages are present."""
        return bool(self.name.strip() and self.name_ne.strip())


class TaxonomyTerm(models.Model):
    vocabulary = models.CharField(30, choices=TermVocabulary.choices, db_index=True)
    label = NFCCharField(150)
    slug = NFCSlugField(170, allow_unicode=True)
    description = NFCTextField(blank=True)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
    )
    sort_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["vocabulary", "sort_order", "label"]
        constraints: typing.ClassVar[list] = [
            models.UniqueConstraint(fields=["vocabulary", "slug"], name="uniq_term_vocab_slug"),
            models.UniqueConstraint(fields=["vocabulary", "label"], name="uniq_term_vocab_label"),
        ]
        indexes: typing.ClassVar[list] = [
            models.Index(fields=["vocabulary", "is_active"], name="idx_term_vocab_active"),
        ]

    def __str__(self):
        return f"{self.get_vocabulary_display()}: {self.label}"


class ApprovedLicense(models.Model):
    spdx_id = models.CharField(
        80,
        unique=True,
        validators=[RegexValidator(r"^[A-Za-z0-9.+-]+$")],
    )
    name = NFCCharField(200)
    reference_url = models.URLField(blank=True)
    use = models.CharField(max_length=16, choices=LicenseUse.choices, default=LicenseUse.CODE)
    legal_reference = NFCCharField(60, blank=True, default="")
    legal_approved_on = models.DateField(null=True, blank=True)
    is_approved = models.BooleanField(default=False)
    is_default = models.BooleanField(default=False)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["spdx_id"]
        verbose_name = "approved license"

    def __str__(self):
        return f"{self.spdx_id} ({self.name})"


class SkillSuggestion(models.Model):
    suggested_by = models.ForeignKey(
        "accounts.User",
        null=True,
        on_delete=models.SET_NULL,
        related_name="skill_suggestions",
    )
    term_name = NFCCharField(100)
    note = NFCTextField(blank=True)
    status = models.CharField(
        10,
        choices=SuggestionStatus.choices,
        default=SuggestionStatus.PENDING,
    )
    resolved_by = models.ForeignKey(
        "accounts.User",
        null=True,
        on_delete=models.SET_NULL,
        related_name="resolved_suggestions",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["-created_at"]
        constraints: typing.ClassVar[list] = [
            models.UniqueConstraint(fields=["term_name"], name="uniq_suggestion_term"),
            models.UniqueConstraint(
                models.functions.Lower("term_name"), name="uniq_suggestion_term_ci"
            ),
        ]

    def __str__(self):
        return f"Suggestion: {self.term_name}"


class TaxonomyVersion(models.Model):
    """ADM-001/D5.5: one numbered, attributed change to the skills taxonomy.

    The prototype states that every change creates a new taxonomy version with a
    diff and the name of the Super Admin who made it, so the catalogue can be
    read back as a history rather than only as its current state.
    """

    version = models.PositiveIntegerField(unique=True)
    action = models.CharField(max_length=12, choices=TaxonomyChangeAction.choices)
    subject = models.ForeignKey(
        "taxonomy.Skill",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="versions",
    )
    subject_label = NFCCharField(150)
    summary = NFCTextField(blank=True, default="")
    diff = models.JSONField(default=dict, blank=True)
    actor = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="taxonomy_versions"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["-version"]
        verbose_name = "taxonomy version"
        verbose_name_plural = "taxonomy versions"

    def __str__(self) -> str:
        return f"v{self.version} · {self.get_action_display()} {self.subject_label}"
