from django.contrib import admin

from apps.administration.audit_admin import ReadOnlyModelAdmin
from apps.blogs.models import BlogPost, BlogVersion


@admin.register(BlogPost)
class BlogPostAdmin(ReadOnlyModelAdmin, admin.ModelAdmin):
    list_display = (
        "title",
        "author",
        "status",
        "moderation_state",
        "is_official",
        "language",
        "published_at",
    )
    list_filter = ("status", "moderation_state", "is_official", "language")
    search_fields = ("title", "excerpt", "canonical_url")


@admin.register(BlogVersion)
class BlogVersionAdmin(ReadOnlyModelAdmin, admin.ModelAdmin):
    list_display = ("post", "version_number", "created_by", "created_at")
    list_filter = ("post__status",)
    search_fields = ("post__title",)
