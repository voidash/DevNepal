from django.contrib import admin

from apps.administration.audit_admin import AuditedModelAdmin, ReadOnlyModelAdmin
from apps.recognition.models import Badge, BadgeAward, ScoringPolicy


@admin.register(Badge)
class BadgeAdmin(AuditedModelAdmin, admin.ModelAdmin):
    """ADM-001/REC-007: badge definitions with documented, versioned criteria."""

    list_display = ("name", "slug", "kind", "criteria_version", "is_active")
    list_filter = ("kind", "is_active")
    search_fields = ("name", "slug", "description")


@admin.register(BadgeAward)
class BadgeAwardAdmin(ReadOnlyModelAdmin, admin.ModelAdmin):
    """ADM-001/REC-004: awards stay auditable; revocation happens in the recognition surface."""

    list_display = ("badge", "recipient", "status", "issuer", "issued_at")
    list_filter = ("status",)
    search_fields = ("badge__name", "recipient__username")
    list_select_related = ("badge", "recipient", "issuer")
    ordering = ("-issued_at",)


@admin.register(ScoringPolicy)
class ScoringPolicyAdmin(ReadOnlyModelAdmin, admin.ModelAdmin):
    """ADM-001/REC-005: published scoring policy versions."""

    list_display = ("version", "activated_at", "approved_by", "is_active")
    list_filter = ("is_active",)
