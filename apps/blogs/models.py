import typing

from django.db import models

from apps.accounts.fields import NormalizedURLField
from apps.blogs.enums import BlogModerationState, BlogPostType, BlogStatus
from apps.taxonomy.enums import ContentLanguage
from apps.taxonomy.fields import NFCCharField, NFCTextField


class BlogPost(models.Model):
    """A native safe-Markdown post or an external article reference."""

    author = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="blog_posts",
    )
    title = NFCCharField(200)
    excerpt = NFCTextField(blank=True)
    post_type = models.CharField(
        max_length=10,
        choices=BlogPostType.choices,
        default=BlogPostType.EXTERNAL,
        db_index=True,
    )
    content_markdown = NFCTextField(blank=True)
    content_rendered = models.TextField(blank=True, editable=False)
    canonical_url = NormalizedURLField(blank=True)
    cover_image_url = NormalizedURLField(blank=True)
    cover_image_alt = NFCCharField(max_length=300, blank=True)
    tags = models.ManyToManyField(
        "taxonomy.TaxonomyTerm",
        blank=True,
        related_name="blog_posts",
    )
    language = models.CharField(
        2,
        choices=ContentLanguage.choices,
        default=ContentLanguage.ENGLISH,
    )
    reading_time_minutes = models.PositiveIntegerField(default=0)
    status = models.CharField(
        12,
        choices=BlogStatus.choices,
        default=BlogStatus.DRAFT,
        db_index=True,
    )
    moderation_state = models.CharField(
        15,
        choices=BlogModerationState.choices,
        default=BlogModerationState.NOT_REVIEWED,
    )
    is_official = models.BooleanField(default=False)
    official_published_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="official_blog_posts",
    )
    official_project = models.ForeignKey(
        "projects.Project",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="official_blog_posts",
    )
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["-published_at", "-id"]
        indexes: typing.ClassVar[list] = [
            models.Index(fields=["status", "-published_at"], name="idx_blog_status_published"),
            models.Index(fields=["author", "-published_at"], name="idx_blog_author_published"),
            models.Index(fields=["language", "status"], name="idx_blog_language_status"),
        ]
        constraints: typing.ClassVar[list] = [
            models.CheckConstraint(
                condition=models.Q(is_official=False)
                | (
                    models.Q(official_published_by__isnull=False)
                    & models.Q(official_project__isnull=False)
                ),
                name="chk_official_blog_provenance",
            ),
        ]

    def __str__(self):
        return self.title


class BlogVersion(models.Model):
    post = models.ForeignKey(
        BlogPost,
        on_delete=models.CASCADE,
        related_name="versions",
    )
    version_number = models.PositiveIntegerField()
    snapshot = models.JSONField(default=dict)
    created_by = models.ForeignKey(
        "accounts.User",
        null=True,
        on_delete=models.SET_NULL,
        related_name="blog_versions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["post", "-version_number"]
        constraints: typing.ClassVar[list] = [
            models.UniqueConstraint(
                fields=["post", "version_number"],
                name="uniq_blog_version_number",
            ),
        ]
        indexes: typing.ClassVar[list] = [
            models.Index(fields=["post", "-created_at"], name="idx_blogversion_post_created"),
        ]

    def __str__(self):
        return f"{self.post} v{self.version_number}"
