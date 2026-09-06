from django.contrib import admin

from apps.administration.audit_admin import ReadOnlyModelAdmin
from apps.moderation.models import ModerationCase, ModerationEvent, Report


@admin.register(Report)
class ReportAdmin(ReadOnlyModelAdmin, admin.ModelAdmin):
    """ADM-003: structured reports raised against profiles, projects, and content."""

    list_display = ("id", "reason", "reporter", "created_at")
    list_filter = ("reason",)
    search_fields = ("details", "evidence_url", "reporter__username")
    list_select_related = ("reporter",)
    ordering = ("-created_at",)


@admin.register(ModerationCase)
class ModerationCaseAdmin(ReadOnlyModelAdmin, admin.ModelAdmin):
    """ADM-002/ADM-004: case triage state; decisions are recorded in the case surface."""

    list_display = ("id", "status", "assigned_to", "created_at", "updated_at")
    list_filter = ("status",)
    search_fields = ("report__details", "assigned_to__username")
    list_select_related = ("report", "assigned_to")
    ordering = ("-created_at",)


@admin.register(ModerationEvent)
class ModerationEventAdmin(ReadOnlyModelAdmin, admin.ModelAdmin):
    """ADM-004/ADM-008: the per-case history is readable and never editable."""

    list_display = ("case", "event", "actor", "created_at")
    list_filter = ("event",)
    search_fields = ("case__id", "actor__username")
    list_select_related = ("case", "actor")
    ordering = ("-created_at",)
    actions = None
