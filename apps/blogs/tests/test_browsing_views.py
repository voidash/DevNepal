import pytest
from django.test import override_settings
from django.urls import reverse
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.blogs.enums import BlogModerationState, BlogStatus
from apps.blogs.services import publish_listing
from apps.blogs.tests.factories import BlogPostFactory, TagFactory, UserFactory
from apps.ministries.tests.factories import MinistryPublisherFactory
from apps.projects.enums import ProjectStatus
from apps.projects.tests.factories import ProjectFactory

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
        reverse("blogs:link_external"),
        {
            "title": "Public infrastructure notes",
            "excerpt": "A link to the full article.",
            "canonical_url": "https://medium.com/@author/infrastructure",
            "language": "en",
            "reading_time_minutes": 4,
            "rights_confirmed": "on",
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


@pytest.mark.integration
def test_publisher_can_publish_an_official_project_post_from_the_edit_screen(client):
    """BLG-007/AUTH-005: an MFA-verified publisher selects an assigned ministry project."""
    publisher = MinistryPublisherFactory()
    project = ProjectFactory(
        ministry=publisher.ministry,
        status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
    )
    post = BlogPostFactory(author=publisher.user)
    client.force_login(publisher.user)
    device = TOTPDevice.objects.get(user=publisher.user)
    token = totp(
        device.bin_key,
        step=device.step,
        t0=device.t0,
        digits=device.digits,
        drift=device.drift,
    )
    mfa_response = client.post(reverse("accounts:mfa_setup"), {"token": token})

    assert mfa_response.status_code == 302

    edit_response = client.get(reverse("blogs:edit", kwargs={"post_id": post.pk}))

    assert edit_response.status_code == 200
    assert "Publish as ministry" in edit_response.content.decode()
    assert str(project.pk) in edit_response.content.decode()

    publish_response = client.post(
        reverse("blogs:publish_official", kwargs={"post_id": post.pk}),
        {"project": project.pk},
    )

    assert publish_response.status_code == 302
    post.refresh_from_db()
    assert post.status == BlogStatus.PUBLISHED
    assert post.is_official is True
    assert post.official_published_by == publisher.user
    assert post.official_project == project

    public_response = client.get(reverse("blogs:detail", kwargs={"post_id": post.pk}))

    assert public_response.status_code == 200
    assert project.localized_title in public_response.content.decode()
    assert (
        reverse("projects:detail", kwargs={"slug": project.slug})
        in public_response.content.decode()
    )


@pytest.mark.integration
def test_regular_member_cannot_see_or_submit_official_publication(client):
    """BLG-007: a member has only the personal publication path."""
    member = UserFactory()
    post = BlogPostFactory(author=member)
    client.force_login(member)

    edit_response = client.get(reverse("blogs:edit", kwargs={"post_id": post.pk}))

    assert edit_response.status_code == 200
    assert "Publish as ministry" not in edit_response.content.decode()

    publish_response = client.post(
        reverse("blogs:publish_official", kwargs={"post_id": post.pk}),
        {},
    )

    assert publish_response.status_code == 400
    post.refresh_from_db()
    assert post.status == BlogStatus.DRAFT
    assert post.is_official is False
