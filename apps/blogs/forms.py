from django import forms
from django.utils.translation import gettext_lazy as _

from apps.blogs.enums import BlogPostType
from apps.blogs.services import (
    BlogContentError,
    BlogExternalArticleUrlError,
    clean_external_article_url,
    render_safe_markdown,
)
from apps.ministries.enums import ContactVerificationStatus, OrgStatus, PublisherStatus
from apps.projects.enums import ProjectStatus, ProjectType
from apps.projects.models import Project
from apps.taxonomy.enums import ContentLanguage, TermVocabulary
from apps.taxonomy.models import TaxonomyTerm


class ListingForm(forms.Form):
    post_type = forms.ChoiceField(
        label=_("Publication type"),
        choices=BlogPostType.choices,
        widget=forms.RadioSelect,
        required=False,
    )
    title = forms.CharField(label=_("Title"), max_length=200)
    excerpt = forms.CharField(
        label=_("Excerpt"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    content_markdown = forms.CharField(
        label=_("Article body (Markdown)"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 18}),
        help_text=_("Use headings, links, tables, code blocks, and images with alternative text."),
    )
    canonical_url = forms.URLField(
        label=_("Canonical or external article URL"),
        required=False,
    )
    cover_image_url = forms.URLField(label=_("Cover image URL"), required=False)
    cover_image_alt = forms.CharField(
        label=_("Cover image alternative text"),
        max_length=300,
        required=False,
    )
    tags = forms.ModelMultipleChoiceField(
        label=_("Tags"),
        queryset=TaxonomyTerm.objects.none(),
        required=False,
    )
    language = forms.ChoiceField(label=_("Language"), choices=ContentLanguage.choices)
    reading_time_minutes = forms.IntegerField(
        label=_("Reading time (minutes)"),
        min_value=0,
        required=False,
    )

    def __init__(self, *args, **kwargs):
        post = kwargs.pop("post", None)
        create_native_only = kwargs.pop("create_native_only", False)
        super().__init__(*args, **kwargs)
        self.fields["tags"].queryset = TaxonomyTerm.objects.filter(
            vocabulary=TermVocabulary.TAG,
            is_active=True,
        ).order_by("label")
        if post is not None and not self.is_bound:
            self.initial = {
                "post_type": post.post_type,
                "title": post.title,
                "excerpt": post.excerpt,
                "content_markdown": post.content_markdown,
                "canonical_url": post.canonical_url,
                "cover_image_url": post.cover_image_url,
                "cover_image_alt": post.cover_image_alt,
                "tags": post.tags.all(),
                "language": post.language,
                "reading_time_minutes": post.reading_time_minutes,
            }
        elif post is None and not self.is_bound:
            self.initial["post_type"] = BlogPostType.NATIVE
        if post is not None or create_native_only:
            self.fields["post_type"].disabled = True
        if create_native_only:
            self.fields["post_type"].initial = BlogPostType.NATIVE

    def clean(self):
        cleaned = super().clean()
        post_type = cleaned.get("post_type") or BlogPostType.EXTERNAL
        cleaned["post_type"] = post_type
        markdown = cleaned.get("content_markdown", "")
        canonical_url = cleaned.get("canonical_url", "")
        cover_image_url = cleaned.get("cover_image_url", "")
        cover_image_alt = cleaned.get("cover_image_alt", "")

        if post_type == BlogPostType.EXTERNAL:
            if not canonical_url:
                self.add_error("canonical_url", _("An external article URL is required."))
            if markdown.strip():
                self.add_error(
                    "content_markdown",
                    _("External articles are stored as links only; do not copy the article body."),
                )
        elif post_type == BlogPostType.NATIVE:
            if not markdown.strip():
                self.add_error("content_markdown", _("A native article body is required."))
            else:
                try:
                    cleaned["content_rendered"] = render_safe_markdown(markdown)
                except BlogContentError:
                    self.add_error(
                        "content_markdown",
                        _(
                            "Markdown could not be checked. Review image alternative text, "
                            "URL schemes, and code fences."
                        ),
                    )

        if cover_image_url and not cover_image_alt.strip():
            self.add_error(
                "cover_image_alt",
                _("Alternative text is required when a cover image is provided."),
            )
        if cover_image_alt.strip() and not cover_image_url:
            self.add_error(
                "cover_image_url",
                _("A cover image URL is required when alternative text is provided."),
            )
        return cleaned


class ExternalArticleForm(forms.Form):
    canonical_url = forms.URLField(label=_("Article address"))
    title = forms.CharField(label=_("Article title"), max_length=200)
    excerpt = forms.CharField(
        label=_("Summary"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    tags = forms.ModelMultipleChoiceField(
        label=_("Tags"),
        queryset=TaxonomyTerm.objects.none(),
        required=False,
    )
    language = forms.ChoiceField(label=_("Language"), choices=ContentLanguage.choices)
    reading_time_minutes = forms.IntegerField(
        label=_("Reading time (minutes)"),
        min_value=0,
    )
    rights_confirmed = forms.BooleanField(
        label=_("I am the author of this article, or have the right to list it."),
        required=True,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tags"].queryset = TaxonomyTerm.objects.filter(
            vocabulary=TermVocabulary.TAG,
            is_active=True,
        ).order_by("label")

    def clean_canonical_url(self):
        try:
            return clean_external_article_url(self.cleaned_data["canonical_url"])
        except BlogExternalArticleUrlError as exc:
            raise forms.ValidationError(str(exc)) from exc


class ExternalArticleAddressForm(forms.Form):
    canonical_url = forms.URLField(label=_("Article address"))

    def clean_canonical_url(self):
        try:
            return clean_external_article_url(self.cleaned_data["canonical_url"])
        except BlogExternalArticleUrlError as exc:
            raise forms.ValidationError(str(exc)) from exc


class OfficialPublicationForm(forms.Form):
    project = forms.ModelChoiceField(
        label=_("Project this post is official for"),
        queryset=Project.objects.none(),
        empty_label=_("Select a public ministry project"),
    )

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["project"].queryset = (
            Project.objects.filter(
                project_type=ProjectType.GOVERNMENT,
                status__in=(
                    ProjectStatus.OPEN_FOR_CONTRIBUTION,
                    ProjectStatus.PAUSED,
                    ProjectStatus.COMPLETED,
                ),
                ministry__status=OrgStatus.ACTIVE,
                ministry__publishers__user=actor,
                ministry__publishers__status=PublisherStatus.ACTIVE,
                ministry__publishers__contact_verification_status=ContactVerificationStatus.VERIFIED,
            )
            .select_related("ministry")
            .distinct()
            .order_by("title_en", "pk")
        )
