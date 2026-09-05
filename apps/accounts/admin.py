from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from apps.accounts.models import MemberProfile, MemberSkill, User, UserSession
from apps.administration.audit_admin import ReadOnlyModelAdmin


@admin.register(User)
class UserAdmin(ReadOnlyModelAdmin, DjangoUserAdmin):
    """ADM-001/AUTH-004: named account maintenance, including suspension."""

    list_display = ("username", "email", "first_name", "last_name", "is_active", "is_superuser")
    list_filter = ("is_active", "is_staff", "is_superuser")
    search_fields = ("username", "email", "first_name", "last_name")
    ordering = ("username",)


@admin.register(MemberProfile)
class MemberProfileAdmin(ReadOnlyModelAdmin, admin.ModelAdmin):
    list_display = ("user", "headline", "location", "availability")
    list_filter = ("availability", "province")
    search_fields = ("user__username", "user__email", "headline", "location")
    list_select_related = ("user",)


@admin.register(UserSession)
class UserSessionAdmin(ReadOnlyModelAdmin, admin.ModelAdmin):
    """SEC-005: read-only session visibility; revocation happens in the member surface."""

    list_display = ("user", "device_label", "created_at", "last_activity", "revoked_at")
    search_fields = ("user__username", "device_label")
    list_select_related = ("user",)
    ordering = ("-last_activity",)


@admin.register(MemberSkill)
class MemberSkillAdmin(ReadOnlyModelAdmin, admin.ModelAdmin):
    """ADM-001/PRF-003: the member-to-skill links that power directory search."""

    list_display = ("user", "skill", "self_rating")
    list_filter = ("self_rating",)
    search_fields = ("user__username", "skill__name")
    list_select_related = ("user", "skill")
