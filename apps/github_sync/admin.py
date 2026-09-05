from django.contrib import admin

from apps.administration.audit_admin import ReadOnlyModelAdmin
from apps.github_sync.models import ProviderEvent, RepositoryConnection


@admin.register(RepositoryConnection)
class RepositoryConnectionAdmin(ReadOnlyModelAdmin, admin.ModelAdmin):
    """ADM-006/GIT-004: repository binding and synchronization health."""

    list_display = ("full_name", "project", "sync_state", "last_synced_at")
    list_filter = ("sync_state", "provider")
    search_fields = ("full_name", "project__title_en")
    list_select_related = ("project",)


@admin.register(ProviderEvent)
class ProviderEventAdmin(ReadOnlyModelAdmin, admin.ModelAdmin):
    """ADM-006/GIT-005: webhook intake queue; replay is a runbook operation, not an edit."""

    list_display = ("provider", "event_type", "processing_state", "received_at")
    list_filter = ("provider", "processing_state", "event_type")
    search_fields = ("delivery_id", "event_type")
    ordering = ("-received_at",)
