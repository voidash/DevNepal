from django.contrib import admin

from apps.observability.models import JobRun


@admin.register(JobRun)
class JobRunAdmin(admin.ModelAdmin):
    list_display = ("command", "status", "started_at", "finished_at", "correlation_id")
    list_filter = ("command", "status")
    search_fields = ("command", "correlation_id")
    ordering = ("-started_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
