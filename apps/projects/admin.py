from django.contrib import admin

from apps.administration.audit_admin import ReadOnlyModelAdmin
from apps.projects.models import Application, Project, ProjectReview, ProjectReviewAssignment


@admin.register(Project)
class ProjectAdmin(ReadOnlyModelAdmin, admin.ModelAdmin):
    """ADM-001/GOV-004: project registry maintenance across the publication lifecycle."""

    list_display = ("title_en", "project_type", "status", "ministry", "owner", "deadline")
    list_filter = ("project_type", "status", "difficulty")
    search_fields = ("title_en", "title_ne", "slug", "repository_url")
    list_select_related = ("ministry", "owner")
    autocomplete_fields = ("license",)
    ordering = ("-id",)


@admin.register(ProjectReview)
class ProjectReviewAdmin(ReadOnlyModelAdmin, admin.ModelAdmin):
    """ADM-002/GOV-005: recorded review decisions stay readable but not rewritable."""

    list_display = ("project", "decision", "reviewer", "created_at")
    list_filter = ("decision",)
    search_fields = ("project__title_en", "reviewer__username")
    list_select_related = ("project", "reviewer")
    ordering = ("-created_at",)


@admin.register(ProjectReviewAssignment)
class ProjectReviewAssignmentAdmin(ReadOnlyModelAdmin, admin.ModelAdmin):
    """ADM-002: reviewer assignment and service-level tracking for the PMO queue."""

    list_display = ("project", "reviewer", "assigned_at")
    search_fields = ("project__title_en", "reviewer__username")
    list_select_related = ("project", "reviewer")


@admin.register(Application)
class ApplicationAdmin(ReadOnlyModelAdmin, admin.ModelAdmin):
    """ADM-001/APP-002: participation records across projects."""

    list_display = ("project", "applicant", "kind", "status", "submitted_at")
    list_filter = ("status", "kind")
    search_fields = ("project__title_en", "applicant__username")
    list_select_related = ("project", "applicant")
    ordering = ("-submitted_at",)
