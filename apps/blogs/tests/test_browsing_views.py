import pytest
from django.test import override_settings
from django.urls import reverse

from apps.blogs.enums import BlogModerationState, BlogStatus
from apps.blogs.services import publish_listing
from apps.blogs.tests.factories import BlogPostFactory, TagFactory, UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def blog_urlconf():
    with override_settings(ROOT_URLCONF="apps.blogs.tests.urls"):
        yield


@pytest.mark.unit
def test_public_visitors_browse_published_external_article_listings(client):
    """BLG-005/DSC-001: public visitors browse published external-article links only."""
    author = UserFactory()
    published = publish_listing(author, BlogPostFactory(author=author))
    published.tags.add(TagFactory())
    draft = BlogPostFactory()
    restricted_author = UserFactory()
    restricted = publish_listing(restricted_author, BlogPostFactory(author=restricted_author))
    restricted.moderation_state = BlogModerationState.RESTRICTED
    restricted.save(update_fields=["moderation_state"])

    response = client.get(reverse("blogs:list"))

    assert response.status_code == 200
    assert list(response.context["posts"]) == [published]
    assert published.canonical_url in response.content.decode()
    assert draft not in response.context["posts"]
    assert restricted not in response.context["posts"]


@pytest.mark.unit
def test_public_detail_exposes_only_published_non_restricted_listing(client):
    """BLG-005/BLG-006: public detail never exposes drafts or restricted listings."""
    author = UserFactory()
    published = publish_listing(author, BlogPostFactory(author=author))
    draft = BlogPostFactory()
    restricted_author = UserFactory()
    restricted = publish_listing(restricted_author, BlogPostFactory(author=restricted_author))
    restricted.moderation_state = BlogModerationState.RESTRICTED
    restricted.save(update_fields=["moderation_state"])

    response = client.get(reverse("blogs:detail", kwargs={"post_id": published.pk}))

    assert response.status_code == 200
    assert response.context["post"] == published
    assert client.get(reverse("blogs:detail", kwargs={"post_id": draft.pk})).status_code == 404
    assert client.get(reverse("blogs:detail", kwargs={"post_id": restricted.pk})).status_code == 404


@pytest.mark.unit
def test_author_can_create_edit_and_transition_own_listing(client):
    """BLG-001/BLG-005: an authenticated author manages the external-link listing lifecycle."""
    author = UserFactory()
    client.force_login(author)

    create_response = client.post(
        reverse("blogs:create"),
        {
            "title": "Public infrastructure notes",
            "excerpt": "A link to the full article.",
            "canonical_url": "https://medium.com/@author/infrastructure",
            "language": "en",
            "reading_time_minutes": 4,
        },
    )

    assert create_response.status_code == 302
    post = author.blog_posts.get()
    edit_response = client.post(
        reverse("blogs:edit", kwargs={"post_id": post.pk}),
        {
            "title": "Updated infrastructure notes",
            "excerpt": "A link to the full article.",
            "canonical_url": post.canonical_url,
            "language": "en",
            "reading_time_minutes": 6,
        },
    )

    assert edit_response.status_code == 302
    post.refresh_from_db()
    assert post.title == "Updated infrastructure notes"
    for action, expected_status in (
        ("publish", BlogStatus.PUBLISHED),
        ("unpublish", BlogStatus.UNPUBLISHED),
        ("archive", BlogStatus.ARCHIVED),
    ):
        response = client.post(reverse(f"blogs:{action}", kwargs={"post_id": post.pk}))
        assert response.status_code == 302
        post.refresh_from_db()
        assert post.status == expected_status


@pytest.mark.unit
def test_author_surfaces_require_login_and_never_expose_another_authors_listing(client):
    """BLG-001: author management requires authentication and enforces ownership."""
    post = BlogPostFactory()

    assert client.get(reverse("blogs:create")).status_code == 302

    other_member = UserFactory()
    client.force_login(other_member)
    assert client.get(reverse("blogs:edit", kwargs={"post_id": post.pk})).status_code == 404
    assert client.post(reverse("blogs:publish", kwargs={"post_id": post.pk})).status_code == 404
