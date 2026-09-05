import typing

from django.core.validators import RegexValidator
from django.db import models

from apps.taxonomy.enums import SuggestionStatus, TermVocabulary
from apps.taxonomy.fields import NFCCharField, NFCSlugField, NFCTextField


class Skill(models.Model):
    name = NFCCharField(100)
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
