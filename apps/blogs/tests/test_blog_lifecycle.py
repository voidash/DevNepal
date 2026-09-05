import unicodedata

import pytest

from apps.blogs.enums import BlogStatus
from apps.blogs.services import (
    BlogCanonicalUrlError,
    BlogListingFieldError,
    archive,
    create_listing,
    edit_listing,
    publish_listing,
    unpublish,
)
from apps.blogs.tests.factories import BlogPostFactory, TagFactory, UserFactory
from apps.taxonomy.enums import ContentLanguage

pytestmark = [pytest.mark.django_db]


@pytest.mark.unit
def test_listing_metadata_round_trips_through_create_edit_and_publish():
    """BLG-004: listing metadata (title, excerpt, tags, language, time, pub date, URL) persists."""
    member = UserFactory()
    tags = [TagFactory(), TagFactory()]

    post = create_listing(
        member,
        title="Routing Devanagari through an open pipeline",
        excerpt="Practical notes on normalizing Nepali text.",
        canonical_url="https://medium.com/@writer/devanagari-pipeline",
        tags=tags,
        language=ContentLanguage.NEPALI,
        reading_time_minutes=7,
    )

    assert post.title == "Routing Devanagari through an open pipeline"
    assert post.excerpt == "Practical notes on normalizing Nepali text."
    assert post.canonical_url == "https://medium.com/@writer/devanagari-pipeline"
    assert set(post.tags.values_list("slug", flat=True)) == {tags[0].slug, tags[1].slug}
    assert post.language == ContentLanguage.NEPALI
    assert post.reading_time_minutes == 7
    assert post.status == BlogStatus.DRAFT
    assert post.published_at is None

    publish_listing(member, post)
    post.refresh_from_db()
    assert post.status == BlogStatus.PUBLISHED
    assert post.published_at is not None

    edit_listing(member, post, reading_time_minutes=9, excerpt="Updated notes.")
    post.refresh_from_db()
    assert post.reading_time_minutes == 9
    assert post.excerpt == "Updated notes."


@pytest.mark.unit
def test_canonical_url_must_be_http_https_and_is_normalized():
    """BLG-004: canonical URL is validated against an http/https allowlist and stored normalized."""
    member = UserFactory()

    post = create_listing(
        member,
        title="Case study",
        canonical_url="HTTPS://Medium.Com/@writer/case-study",
    )
    assert post.canonical_url == "https://medium.com/@writer/case-study"

    with pytest.raises(BlogCanonicalUrlError):
        create_listing(member, title="Bad scheme", canonical_url="javascript:alert(1)")
    with pytest.raises(BlogCanonicalUrlError):
        create_listing(member, title="Bad scheme", canonical_url="ftp://example.com/article")
    with pytest.raises(BlogCanonicalUrlError):
        create_listing(member, title="Missing url")


@pytest.mark.unit
def test_listing_rejects_fields_outside_the_link_listing_subset():
    """BLG-005: an external article is listed as a link only; copied full text has nowhere to go."""
    member = UserFactory()

    with pytest.raises(BlogListingFieldError):
        create_listing(
            member,
            title="Copied article",
            canonical_url="https://medium.com/@writer/article",
            content_markdown="# full copied text",
        )


@pytest.mark.unit
def test_listing_lifecycle_supports_unpublish_and_archive():
    """BLG-001 (D13 listing subset): unpublish and archive take effect for the author."""
    member = UserFactory()
    post = publish_listing(member, BlogPostFactory(author=member))

    unpublish(member, post)
    post.refresh_from_db()
    assert post.status == BlogStatus.UNPUBLISHED

    archive(member, post)
    post.refresh_from_db()
    assert post.status == BlogStatus.ARCHIVED


@pytest.mark.unit
def test_devanagari_title_and_excerpt_are_stored_nfc_normalized():
    """DSC-003: mixed NFC/NFD Devanagari input composes to NFC on save."""
    member = UserFactory()
    nfd_text = "\u0928\u093c\u0947\u092a\u093e\u0932\u0940" + "\u0930\u093c"
    nfc_text = unicodedata.normalize("NFC", nfd_text)
    assert nfd_text != nfc_text

    post = create_listing(
        member,
        title=nfd_text,
        excerpt=f"देवनागरी {nfd_text} पाठ प्रशोधन।",
        canonical_url="https://medium.com/@writer/nepali-notes",
    )
    post.refresh_from_db()

    assert post.title == nfc_text
    assert post.excerpt == unicodedata.normalize("NFC", post.excerpt)
    assert post.excerpt != f"देवनागरी {nfd_text} पाठ प्रशोधन।"
