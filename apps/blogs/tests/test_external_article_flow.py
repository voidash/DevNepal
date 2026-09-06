from email.message import Message

import pytest
from django.test import override_settings
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.blogs.enums import BlogPostType
from apps.blogs.services import (
    BlogExternalMetadataError,
    ExternalArticleMetadata,
    fetch_external_article_metadata,
)
from apps.blogs.tests.factories import TagFactory, UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def blog_urlconf():
    with override_settings(ROOT_URLCONF="apps.blogs.tests.urls"):
        yield


@pytest.mark.unit
def test_member_links_an_https_article_after_confirming_provenance(client):
    """BLG-005/MEM-007: a member lists an HTTPS article only after confirming listing rights."""
    member = UserFactory()
    tag = TagFactory()
    client.force_login(member)

    response = client.post(
        reverse("blogs:link_external"),
        {
            "canonical_url": "HTTPS://Medium.COM/@writer/rural-health-posts",
            "title": "Offline-first forms for rural health posts",
            "excerpt": "Lessons from intermittent connectivity.",
            "tags": [tag.pk],
            "language": "en",
            "reading_time_minutes": 11,
            "rights_confirmed": "on",
            "action": "list",
        },
    )

    assert response.status_code == 302
    post = member.blog_posts.get()
    assert response.url == reverse("blogs:edit", kwargs={"post_id": post.pk})
    assert post.post_type == BlogPostType.EXTERNAL
    assert post.canonical_url == "https://medium.com/@writer/rural-health-posts"
    assert post.external_rights_confirmed_at is not None
    assert list(post.tags.all()) == [tag]
    audit_event = AuditEvent.objects.get(action="blog.created", object_id=str(post.pk))
    assert audit_event.after["external_rights_confirmed_at"] is not None


@pytest.mark.unit
@pytest.mark.parametrize(
    ("url", "error"),
    [
        ("http://medium.com/@writer/article", "HTTPS"),
        ("https://writer:secret@medium.com/article", "credentials"),
        ("https://127.0.0.1/article", "public hostname"),
        ("https://localhost/article", "public hostname"),
    ],
)
def test_external_article_flow_rejects_unsafe_or_noncanonical_sources(client, url, error):
    """BLG-005/MEM-007: link-only publication rejects unsafe article addresses."""
    member = UserFactory()
    client.force_login(member)

    response = client.post(
        reverse("blogs:link_external"),
        {
            "canonical_url": url,
            "title": "An external article",
            "language": "en",
            "reading_time_minutes": 1,
            "rights_confirmed": "on",
            "action": "list",
        },
    )

    assert response.status_code == 200
    assert error in response.content.decode()
    assert member.blog_posts.count() == 0


@pytest.mark.unit
def test_external_article_flow_requires_a_rights_confirmation(client):
    """BLG-005: a member must affirm authorship or listing permission before publication."""
    member = UserFactory()
    client.force_login(member)

    response = client.post(
        reverse("blogs:link_external"),
        {
            "canonical_url": "https://dev.to/writer/article",
            "title": "An external article",
            "language": "en",
            "reading_time_minutes": 1,
            "action": "list",
        },
    )

    assert response.status_code == 200
    assert "confirm" in response.content.decode().lower()
    assert member.blog_posts.count() == 0


@pytest.mark.unit
def test_link_article_screen_is_authenticated_and_identifies_link_only_scope(client):
    """BLG-005: B4.6 is authenticated and explains that imports are unavailable."""
    assert client.get(reverse("blogs:link_external")).status_code == 302

    member = UserFactory()
    client.force_login(member)
    response = client.get(reverse("blogs:link_external"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Link an article" in content
    assert "Article address" in content
    assert "not available" in content


@pytest.mark.unit
def test_link_article_fetches_editable_metadata_from_a_validated_source(client, monkeypatch):
    """BLG-005/MEM-007: a validated source address pre-fills editable external-article metadata."""
    member = UserFactory()
    client.force_login(member)
    monkeypatch.setattr(
        "apps.blogs.views.fetch_external_article_metadata",
        lambda url: ExternalArticleMetadata(
            canonical_url=url,
            source_name="Medium",
            title="Offline-first forms",
            excerpt="Lessons from rural health posts.",
            language="en",
        ),
    )

    response = client.post(
        reverse("blogs:link_external"),
        {
            "canonical_url": "https://medium.com/@writer/offline-first-forms",
            "action": "fetch",
        },
    )

    assert response.status_code == 200
    assert response.context["source_metadata"].source_name == "Medium"
    assert response.context["form"].initial["title"] == "Offline-first forms"
    assert response.context["form"].initial["excerpt"] == "Lessons from rural health posts."


@pytest.mark.unit
def test_metadata_fetch_parses_only_bounded_html_from_a_pinned_public_address(monkeypatch):
    """BLG-005/MEM-007: metadata fetch pins a public address and extracts safe page metadata."""

    class Response:
        status = 200

        def __init__(self):
            self.headers = Message()
            self.headers["Content-Type"] = "text/html; charset=utf-8"

        def getheader(self, name, default=None):
            return self.headers.get(name, default)

        def read(self, _size):
            return (
                '<html lang="ne"><head><meta property="og:title" content="लेख">'
                '<meta name="description" content="सारांश"></head></html>'
            ).encode()

    class Connection:
        def __init__(self, host, port, address):
            self.host = host
            self.port = port
            self.address = address

        def request(self, method, target, headers):
            assert method == "GET"
            assert target == "/article"
            assert headers["Accept"].startswith("text/html")

        def getresponse(self):
            return Response()

        def close(self):
            return None

    monkeypatch.setattr(
        "apps.blogs.services.socket.getaddrinfo",
        lambda host, port, type: [(None, None, None, None, ("93.184.216.34", port))],
    )
    monkeypatch.setattr("apps.blogs.services._PinnedHTTPSConnection", Connection)

    metadata = fetch_external_article_metadata("https://example.com/article")

    assert metadata == ExternalArticleMetadata(
        canonical_url="https://example.com/article",
        source_name="example.com",
        title="लेख",
        excerpt="सारांश",
        language="ne",
    )


@pytest.mark.unit
def test_metadata_fetch_refuses_hostname_resolving_to_a_nonpublic_address(monkeypatch):
    """MEM-007: metadata retrieval rejects an internal destination before opening a connection."""
    monkeypatch.setattr(
        "apps.blogs.services.socket.getaddrinfo",
        lambda host, port, type: [(None, None, None, None, ("127.0.0.1", port))],
    )

    with pytest.raises(BlogExternalMetadataError, match="public address"):
        fetch_external_article_metadata("https://example.com/article")
