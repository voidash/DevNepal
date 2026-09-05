import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods, require_POST

from apps.blogs.enums import BlogModerationState, BlogPostType, BlogStatus
from apps.blogs.forms import ListingForm
from apps.blogs.models import BlogPost
from apps.blogs.services import (
    BlogServiceError,
    archive,
    create_listing,
    create_native_post,
    edit_listing,
    edit_native_post,
    publish_listing,
    unpublish,
)

logger = logging.getLogger(__name__)


def public_posts():
    return (
        BlogPost.objects.filter(status=BlogStatus.PUBLISHED)
        .exclude(moderation_state=BlogModerationState.RESTRICTED)
        .select_related("author", "official_published_by")
        .prefetch_related("tags")
    )


def author_posts(author):
    return (
        BlogPost.objects.filter(author=author)
        .select_related("author", "official_published_by")
        .prefetch_related("tags")
    )


def _author_post_or_404(author, post_id):
    return get_object_or_404(author_posts(author), pk=post_id)


def _post_fields(form):
    fields = form.cleaned_data.copy()
    post_type = fields.pop("post_type")
    fields.pop("content_rendered", None)
    if post_type == BlogPostType.EXTERNAL:
        fields.pop("content_markdown", None)
        if fields["reading_time_minutes"] is None:
            fields["reading_time_minutes"] = 0
    else:
        fields.pop("reading_time_minutes", None)
    return post_type, fields


def _service_form_error(form):
    form.add_error(None, _("The listing could not be saved. Review the fields and try again."))


def _preview_context(form, post):
    post_type = form.cleaned_data["post_type"]
    preview_html = ""
    if post_type == BlogPostType.NATIVE:
        preview_html = form.cleaned_data["content_rendered"]
    return {
        "form": form,
        "post": post,
        "preview_html": preview_html,
        "preview_checks": [
            _("Executable HTML is escaped."),
            _("Links use HTTP or HTTPS."),
            _("Every image has alternative text."),
        ],
    }


def blog_list(request: HttpRequest) -> HttpResponse:
    """BLG-005/DSC-001: browse published, non-restricted external-article listings."""
    return render(request, "blogs/blog_list.html", {"posts": public_posts()})


def blog_detail(request: HttpRequest, post_id: int) -> HttpResponse:
    """BLG-005/BLG-006: render a public external link without copied article content."""
    post = get_object_or_404(public_posts(), pk=post_id)
    return render(request, "blogs/blog_detail.html", {"post": post})


@login_required(login_url=reverse_lazy("accounts:login"))
def my_blog_list(request: HttpRequest) -> HttpResponse:
    """BLG-001: authors can inspect every state of their own listings."""
    return render(request, "blogs/my_blog_list.html", {"posts": author_posts(request.user)})


@login_required(login_url=reverse_lazy("accounts:login"))
@require_http_methods(["GET", "POST"])
def blog_create(request: HttpRequest) -> HttpResponse:
    """BLG-001/BLG-005: create an author-owned external-article link listing."""
    form = ListingForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if request.POST.get("action") == "preview":
            return render(request, "blogs/blog_form.html", _preview_context(form, None))
        post_type, fields = _post_fields(form)
        try:
            if post_type == BlogPostType.NATIVE:
                post = create_native_post(request.user, **fields)
            else:
                post = create_listing(request.user, **fields)
        except BlogServiceError:
            logger.exception("Blog creation failed for author=%s", request.user.pk)
            _service_form_error(form)
        else:
            return redirect("blogs:edit", post_id=post.pk)
    return render(request, "blogs/blog_form.html", {"form": form, "post": None})


@login_required(login_url=reverse_lazy("accounts:login"))
@require_http_methods(["GET", "POST"])
def blog_edit(request: HttpRequest, post_id: int) -> HttpResponse:
    """BLG-001: edit only the authenticated author's non-archived listing."""
    post = _author_post_or_404(request.user, post_id)
    form = ListingForm(request.POST or None, post=post)
    if request.method == "POST" and form.is_valid():
        if request.POST.get("action") == "preview":
            return render(request, "blogs/blog_form.html", _preview_context(form, post))
        post_type, fields = _post_fields(form)
        try:
            if post_type == BlogPostType.NATIVE:
                edit_native_post(request.user, post, **fields)
            else:
                edit_listing(request.user, post, **fields)
        except BlogServiceError:
            logger.exception("Blog edit failed for author=%s post=%s", request.user.pk, post.pk)
            _service_form_error(form)
        else:
            return redirect("blogs:edit", post_id=post.pk)
    return render(request, "blogs/blog_form.html", {"form": form, "post": post})


def _transition(request: HttpRequest, post_id: int, transition):
    post = _author_post_or_404(request.user, post_id)
    try:
        transition(request.user, post)
    except BlogServiceError:
        logger.exception(
            "Blog transition failed for author=%s post=%s transition=%s",
            request.user.pk,
            post.pk,
            transition.__name__,
        )
        form = ListingForm(post=post)
        _service_form_error(form)
        return render(request, "blogs/blog_form.html", {"form": form, "post": post}, status=400)
    return redirect("blogs:mine")


@login_required(login_url=reverse_lazy("accounts:login"))
@require_POST
def blog_publish(request: HttpRequest, post_id: int) -> HttpResponse:
    """BLG-001: publish an author-owned listing through the lifecycle service."""
    return _transition(request, post_id, publish_listing)


@login_required(login_url=reverse_lazy("accounts:login"))
@require_POST
def blog_unpublish(request: HttpRequest, post_id: int) -> HttpResponse:
    """BLG-001: unpublish an author-owned listing through the lifecycle service."""
    return _transition(request, post_id, unpublish)


@login_required(login_url=reverse_lazy("accounts:login"))
@require_POST
def blog_archive(request: HttpRequest, post_id: int) -> HttpResponse:
    """BLG-001: archive an author-owned listing through the lifecycle service."""
    return _transition(request, post_id, archive)
