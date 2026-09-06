from django.contrib import admin

from apps.administration.audit_admin import ReadOnlyModelAdmin
from apps.notifications.models import Notification, NotificationPreference


@admin.register(Notification)
class NotificationAdmin(ReadOnlyModelAdmin, admin.ModelAdmin):
    """ADM-006/NTF-004: delivery state visibility for the operations dashboard."""

    list_display = ("recipient", "type", "channel", "delivery_status", "created_at", "read_at")
    list_filter = ("delivery_status", "type", "channel")
    search_fields = ("recipient__username",)
    list_select_related = ("recipient",)
    ordering = ("-created_at",)


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(ReadOnlyModelAdmin, admin.ModelAdmin):
    list_display = (
        "user",
        "digest_frequency",
        "email_applications",
        "email_reviews",
        "email_contributions",
        "email_community",
    )
    list_filter = ("digest_frequency", "email_applications", "email_reviews")
    search_fields = ("user__username",)
    list_select_related = ("user",)
