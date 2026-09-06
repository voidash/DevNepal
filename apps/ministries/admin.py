from django.contrib import admin

from apps.administration.audit_admin import ReadOnlyModelAdmin
from apps.ministries.models import MinistryOrganization, MinistryPublisher


@admin.register(MinistryOrganization)
class MinistryOrganizationAdmin(ReadOnlyModelAdmin, admin.ModelAdmin):
    """ADM-001/GOV-001: ministry provisioning, suspension, and revocation records."""

    list_display = ("name_en", "abbreviation", "slug", "status", "provisioned_at")
    list_filter = ("status",)
    search_fields = ("name_en", "name_ne", "abbreviation", "slug", "contact_email")
    readonly_fields = ("provisioned_by", "provisioned_at", "created_at", "updated_at")
    ordering = ("name_en",)


@admin.register(MinistryPublisher)
class MinistryPublisherAdmin(ReadOnlyModelAdmin, admin.ModelAdmin):
    """ADM-001/GOV-002: named officer accounts; shared ministry credentials are not allowed."""

    list_display = ("user", "ministry", "title", "status", "contact_verification_status")
    list_filter = ("status", "contact_verification_status")
    search_fields = ("user__username", "official_email", "title", "ministry__name_en")
    list_select_related = ("user", "ministry")
    readonly_fields = ("assigned_by", "assigned_at", "revoked_by", "revoked_at")
