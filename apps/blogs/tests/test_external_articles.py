import pytest

from apps.blogs.enums import BlogStatus
from apps.blogs.services import BlogListingFieldError, create_listing, publish_listing
from apps.blogs.tests.factories import TagFactory, UserFactory
from apps.taxonomy.enums import ContentLanguage, TermVocabulary
from apps.taxonomy.tests.factories import TaxonomyTermFactory

pytestmark = [pytest.mark.django_db]


@pytest.mark.unit
def test_external_article_is_listed_as_link_only():
    """BLG-005: an external Medium article appears as a link listing without any copied text."""
    member = UserFactory()
    tags = [TagFactory(), TagFactory()]

    post = create_listing(
        member,
        title="What I learned auditing Nepal's open data portals",
        excerpt="A short pointer to my write-up.",
        canonical_url="https://medium.com/@writer/auditing-open-data-portals-97be",
        tags=tags,
        language=ContentLanguage.ENGLISH,
        reading_time_minutes=6,
    )
    publish_listing(member, post)

    post.refresh_from_db()
    assert post.status == BlogStatus.PUBLISHED
    assert post.canonical_url == "https://medium.com/@writer/auditing-open-data-portals-97be"
    assert post.published_at is not None

    post.refresh_from_db()
    assert post.content_markdown == ""
    assert post.content_rendered == ""


@pytest.mark.unit
def test_tag_terms_must_come_from_the_tag_vocabulary():
    """BLG-004: tags are taxonomy TAG terms; other vocabularies are rejected."""
    member = UserFactory()
    contribution_type = TaxonomyTermFactory(vocabulary=TermVocabulary.CONTRIBUTION_TYPE)

    with pytest.raises(BlogListingFieldError):
        create_listing(
            member,
            title="Mistagged listing",
            canonical_url="https://medium.com/@writer/mistagged",
            tags=[contribution_type],
        )
