from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as DjangoGroupAdmin
from django.contrib.auth.models import Group
from django_otp.plugins.otp_totp.admin import TOTPDeviceAdmin as OtpTOTPDeviceAdmin
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.accounts.permissions import is_super_admin
from apps.administration.audit_admin import AuditedModelAdmin, ReadOnlyModelAdmin
from apps.administration.models import FeatureFlag, FeatureFlagChange

admin.site.unregister(Group)
admin.site.unregister(TOTPDevice)


@admin.register(Group)
class AuditedGroupAdmin(AuditedModelAdmin, DjangoGroupAdmin):
    """SEC-008/AUTH-004: permission-group changes are privileged and must be audited."""


@admin.register(TOTPDevice)
class AuditedTOTPDeviceAdmin(AuditedModelAdmin, OtpTOTPDeviceAdmin):
    """SEC-008/AUTH-005: adding or removing an MFA device is an audited security event."""


@admin.register(FeatureFlag)
class FeatureFlagAdmin(AuditedModelAdmin, admin.ModelAdmin):
    """ADM-001: reference maintenance for capability switches."""

    list_display = ("key", "label", "is_enabled", "updated_by", "updated_at")
    list_filter = ("is_enabled",)
    search_fields = ("key", "label", "description")
    readonly_fields = ("updated_by", "created_at", "updated_at")
    ordering = ("key",)

    def has_module_permission(self, request):
        return is_super_admin(request.user)


@admin.register(FeatureFlagChange)
class FeatureFlagChangeAdmin(ReadOnlyModelAdmin, admin.ModelAdmin):
    """D5.7/ADM-008: the versioned change log is readable and never rewritten here."""

    list_display = ("flag", "version", "to_enabled", "status", "proposed_by", "approved_by")
    list_filter = ("status", "to_enabled")
    search_fields = ("flag__key", "reason", "proposed_by__username")
    list_select_related = ("flag", "proposed_by", "approved_by")
