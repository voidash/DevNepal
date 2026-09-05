import unicodedata

import pytest
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError

from apps.audit.models import AuditEvent
from apps.blogs.enums import BlogModerationState, BlogStatus
from apps.blogs.models import BlogPost
from apps.blogs.services import (
    BlogModerationTransitionError,
    BlogOwnershipError,
    BlogStateError,
    OfficialPostPermissionError,
    OfficialPostProjectError,
    OfficialSealWordingError,
    create_listing,
    edit_listing,
    flag_post,
    publish_listing,
    publish_official,
    reinstate_post,
    restrict_post,
)
from apps.blogs.tests.factories import BlogPostFactory, UserFactory
from apps.ministries.enums import PublisherStatus
from apps.ministries.tests.factories import MinistryPublisherFactory
from apps.projects.enums import ProjectStatus
from apps.projects.tests.factories import ProjectFactory

pytestmark = [pytest.mark.django_db]


@pytest.mark.integration
def test_report_moves_post_into_moderation_state():
    """BLG-006: flagging a reported post moves it into a moderation state (contenttypes target)."""
    member = UserFactory()
    post = publish_listing(member, BlogPostFactory(author=member))

    flagged = flag_post(member, post)

    assert flagged.moderation_state == BlogModerationState.UNDER_REVIEW

    content_type = ContentType.objects.get_for_model(BlogPost)
    assert content_type.app_label == "blogs"
    assert content_type.model == "blogpost"


@pytest.mark.integration
def test_moderator_sees_preserved_version_and_audit_history():
    """BLG-006: version and audit history survive edits and moderation of a reported post."""
    member = UserFactory()
    post = create_listing(
        member,
        title="Draft one",
        canonical_url="https://medium.com/@writer/history",
    )
    publish_listing(member, post)
    edit_listing(member, post, title="Draft two")
    flag_post(member, post)
    restrict_post(member, post)

    version_numbers = list(
        post.versions.order_by("version_number").values_list("version_number", flat=True)
    )
    assert version_numbers == [1, 2, 3]
    snapshots = [v.snapshot.get("title") for v in post.versions.order_by("version_number")]
    assert snapshots == ["Draft one", "Draft one", "Draft two"]

    actions = set(
        AuditEvent.objects.filter(
            content_type=ContentType.objects.get_for_model(BlogPost),
            object_id=str(post.pk),
        ).values_list("action", flat=True)
    )
    assert {
        "blog.created",
        "blog.published",
        "blog.edited",
        "blog.moderation.flagged",
        "blog.moderation.restricted",
    } <= actions


@pytest.mark.integration
def test_moderation_state_transitions_are_governed():
    """BLG-006: moderation transitions under review -> restricted -> reinstated; typed errors."""
    member = UserFactory()
    post = publish_listing(member, BlogPostFactory(author=member))

    with pytest.raises(BlogModerationTransitionError):
        restrict_post(member, BlogPostFactory())

    flagged = flag_post(member, post)
    restricted = restrict_post(member, flagged)
    reinstated = reinstate_post(member, restricted)

    assert reinstated.moderation_state == BlogModerationState.REINSTATED
    assert reinstated.status == BlogStatus.PUBLISHED


@pytest.mark.integration
def test_official_publishing_denied_without_publisher_role():
    """BLG-007: a member without official publishing permission is denied, with audit evidence."""
    member = UserFactory()
    post = BlogPostFactory(author=member)

    with pytest.raises(OfficialPostPermissionError):
        publish_official(member, post)

    revoked_publisher = MinistryPublisherFactory(status=PublisherStatus.REVOKED)
    post.author = revoked_publisher.user
    post.save(update_fields=["author"])
    with pytest.raises(OfficialPostPermissionError):
        publish_official(revoked_publisher.user, post)

    post.refresh_from_db()
    assert post.is_official is False
    assert post.status == BlogStatus.DRAFT

    denied = AuditEvent.objects.filter(
        content_type=ContentType.objects.get_for_model(BlogPost),
        object_id=str(post.pk),
        action="blog.official.denied",
        result="failure",
    )
    assert denied.count() == 2


@pytest.mark.integration
def test_active_publisher_publishes_official_with_boolean_label_contract():
    """BLG-007: active publisher publishes official; is_official is the label contract."""
    publisher = MinistryPublisherFactory()
    project = ProjectFactory(
        ministry=publisher.ministry,
        status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
    )
    post = BlogPostFactory(author=publisher.user)

    published = publish_official(publisher.user, post, project=project)

    assert published.is_official is True
    assert published.official_published_by == publisher.user
    assert published.official_project == project
    assert published.status == BlogStatus.PUBLISHED
    assert published.published_at is not None

    event = AuditEvent.objects.get(
        content_type=ContentType.objects.get_for_model(BlogPost),
        object_id=str(post.pk),
        action="blog.published.official",
    )
    assert event.actor == publisher.user
    assert event.after["is_official"] is True


@pytest.mark.integration
def test_official_post_provenance_is_enforced_by_the_database():
    """BLG-007: no official row can omit its accountable publisher or public project."""
    publisher = MinistryPublisherFactory()

    with pytest.raises(IntegrityError):
        BlogPost.objects.create(
            author=publisher.user,
            title="Unaudited official statement",
            is_official=True,
        )


@pytest.mark.integration
def test_official_publication_rejects_a_different_publisher_as_author():
    """BLG-007/SEC-005: a publisher cannot officially publish another author's post."""
    author = MinistryPublisherFactory()
    other_publisher = MinistryPublisherFactory()
    post = BlogPostFactory(author=author.user)

    with pytest.raises(BlogOwnershipError):
        publish_official(other_publisher.user, post)

    post.refresh_from_db()
    assert post.status == BlogStatus.DRAFT
    assert post.is_official is False
    assert AuditEvent.objects.filter(
        actor=other_publisher.user,
        action="blog.official.denied",
        content_type=ContentType.objects.get_for_model(BlogPost),
        object_id=str(post.pk),
        result="failure",
    ).exists()


@pytest.mark.integration
def test_official_publication_rejects_an_unverified_publisher_session():
    """BLG-007/AUTH-005: an official publication requires a verified MFA session."""
    publisher = MinistryPublisherFactory()
    project = ProjectFactory(
        ministry=publisher.ministry,
        status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
    )
    publisher.user.is_verified = lambda: False
    post = BlogPostFactory(author=publisher.user)

    with pytest.raises(OfficialPostPermissionError):
        publish_official(publisher.user, post, project=project)

    post.refresh_from_db()
    assert post.status == BlogStatus.DRAFT
    assert post.is_official is False
    assert AuditEvent.objects.filter(
        actor=publisher.user,
        action="blog.official.denied",
        content_type=ContentType.objects.get_for_model(BlogPost),
        object_id=str(post.pk),
        result="failure",
    ).exists()


@pytest.mark.integration
def test_official_publication_rejects_a_project_outside_the_publisher_ministry():
    """BLG-007: an official post cannot be attributed to a different ministry's project."""
    publisher = MinistryPublisherFactory()
    other_project = ProjectFactory(status=ProjectStatus.OPEN_FOR_CONTRIBUTION)
    post = BlogPostFactory(author=publisher.user)

    with pytest.raises(OfficialPostProjectError):
        publish_official(publisher.user, post, project=other_project)

    post.refresh_from_db()
    assert post.status == BlogStatus.DRAFT
    assert post.official_project is None
    assert AuditEvent.objects.filter(
        actor=publisher.user,
        action="blog.official.denied",
        content_type=ContentType.objects.get_for_model(BlogPost),
        object_id=str(post.pk),
        result="failure",
    ).exists()


@pytest.mark.integration
@pytest.mark.parametrize(
    ("status", "moderation_state"),
    [
        (BlogStatus.ARCHIVED, BlogModerationState.NOT_REVIEWED),
        (BlogStatus.DRAFT, BlogModerationState.UNDER_REVIEW),
        (BlogStatus.DRAFT, BlogModerationState.RESTRICTED),
    ],
)
def test_official_publication_rejects_invalid_source_or_moderation_state(status, moderation_state):
    """BLG-006/BLG-007: archived or moderated posts cannot become official publications."""
    publisher = MinistryPublisherFactory()
    post = BlogPostFactory(
        author=publisher.user,
        status=status,
        moderation_state=moderation_state,
    )

    with pytest.raises(BlogStateError):
        publish_official(publisher.user, post)

    post.refresh_from_db()
    assert post.status == status
    assert post.is_official is False
    assert AuditEvent.objects.filter(
        actor=publisher.user,
        action="blog.official.denied",
        content_type=ContentType.objects.get_for_model(BlogPost),
        object_id=str(post.pk),
        result="failure",
    ).exists()


@pytest.mark.integration
def test_personal_post_with_official_seal_wording_is_blocked_english():
    """BR-009: personal listings must not carry official-seal wording in title or excerpt."""
    member = UserFactory()

    with pytest.raises(OfficialSealWordingError):
        create_listing(
            member,
            title="Government of Nepal official notice",
            canonical_url="https://medium.com/@writer/notice",
        )
    with pytest.raises(OfficialSealWordingError):
        create_listing(
            member,
            title="My notes",
            excerpt="Issued under the official seal of the ministry.",
            canonical_url="https://medium.com/@writer/notes",
        )
    with pytest.raises(OfficialSealWordingError):
        publish_listing(
            member,
            BlogPostFactory(
                author=member,
                title="official seal notice",
                canonical_url="https://medium.com/@writer/seal",
            ),
        )


@pytest.mark.integration
def test_personal_post_with_official_seal_wording_is_blocked_nepali():
    """BR-009: Nepali official-seal wording is blocked even when it arrives NFD-decomposed."""
    member = UserFactory()
    nfd_title = unicodedata.normalize("NFD", "नेपाल सरकारको सूचना")
    nfd_excerpt = unicodedata.normalize("NFD", "श्रीमान् प्रमुखको फ़रमान।")

    with pytest.raises(OfficialSealWordingError):
        create_listing(
            member,
            title=nfd_title,
            canonical_url="https://medium.com/@writer/suchana",
        )
    with pytest.raises(OfficialSealWordingError):
        edit_listing(
            member,
            BlogPostFactory(author=member),
            excerpt=nfd_excerpt,
        )
