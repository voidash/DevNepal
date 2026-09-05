import typing

from django.contrib import admin

from apps.administration.audit_admin import AuditedModelAdmin, ReadOnlyModelAdmin
from apps.taxonomy.models import ApprovedLicense, Skill, SkillSuggestion, TaxonomyTerm


@admin.register(Skill)
class SkillAdmin(AuditedModelAdmin, admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    prepopulated_fields: typing.ClassVar[dict] = {"slug": ("name",)}


@admin.register(TaxonomyTerm)
class TaxonomyTermAdmin(AuditedModelAdmin, admin.ModelAdmin):
    list_display = ("vocabulary", "label", "slug", "parent", "sort_order", "is_active")
    list_filter = ("vocabulary", "is_active")
    search_fields = ("label", "slug")
    prepopulated_fields: typing.ClassVar[dict] = {"slug": ("label",)}


@admin.register(ApprovedLicense)
class ApprovedLicenseAdmin(AuditedModelAdmin, admin.ModelAdmin):
    list_display = ("spdx_id", "name", "is_approved", "is_default")
    list_filter = ("is_approved", "is_default")
    search_fields = ("spdx_id", "name")


@admin.register(SkillSuggestion)
class SkillSuggestionAdmin(ReadOnlyModelAdmin, admin.ModelAdmin):
    list_display = (
        "term_name",
        "status",
        "suggested_by",
        "resolved_by",
        "resolved_at",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = ("term_name", "note")
