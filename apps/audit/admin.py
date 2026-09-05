from django.contrib import admin

from apps.accounts.permissions import is_super_admin
from apps.audit.models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    """ADM-008/SEC-008: view-only registry of the append-only audit trail."""

    list_display = ("created_at", "actor", "action", "object_reference", "result", "correlation_id")
    list_filter = ("result", "source")
    search_fields = ("action", "object_id", "correlation_id")
    list_select_related = ("actor", "content_type")
    ordering = ("-created_at",)
    list_per_page = 25
    actions = None

    @admin.display(description="Object")
    def object_reference(self, event):
        if event.content_type:
            return f"{event.content_type} #{event.object_id}"
        return event.object_id

    def has_view_permission(self, request, obj=None):
        return is_super_admin(request.user)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
