import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.accounts.enums import Visibility
from apps.accounts.tests.factories import MemberLinkFactory, MemberProfileFactory, UserFactory
from apps.blogs.enums import BlogPostType, BlogStatus
from apps.blogs.tests.factories import BlogPostFactory
from apps.contributions.enums import VerificationStatus
from apps.contributions.tests.factories import ContributionRecordFactory
from apps.projects.enums import ApplicationStatus, ProjectStatus
from apps.projects.tests.factories import (
    ApplicationFactory,
    PersonalProjectFactory,
    ProjectFactory,
)
from apps.recognition.enums import AwardStatus
from apps.recognition.tests.factories import BadgeAwardFactory, BadgeFactory
from apps.taxonomy.enums import TermVocabulary
from apps.taxonomy.tests.factories import TaxonomyTermFactory

pytestmark = pytest.mark.django_db


def build_portfolio(user):
    owned_open = PersonalProjectFactory(owner=user, status=ProjectStatus.OPEN_FOR_CONTRIBUTION)
    owned_completed = PersonalProjectFactory(owner=user, status=ProjectStatus.COMPLETED)
    PersonalProjectFactory(owner=user, status=ProjectStatus.DRAFT)
    other_project = PersonalProjectFactory(status=ProjectStatus.OPEN_FOR_CONTRIBUTION)

    joined = ProjectFactory(status=ProjectStatus.OPEN_FOR_CONTRIBUTION)
    ApplicationFactory(project=joined, applicant=user, status=ApplicationStatus.ACCEPTED)
    declined_project = ProjectFactory(status=ProjectStatus.OPEN_FOR_CONTRIBUTION)
    ApplicationFactory(project=declined_project, applicant=user, status=ApplicationStatus.DECLINED)

    published = BlogPostFactory(author=user, status=BlogStatus.PUBLISHED)
    draft = BlogPostFactory(author=user, status=BlogStatus.DRAFT)

    engineering = TaxonomyTermFactory(
        vocabulary=TermVocabulary.CONTRIBUTION_TYPE, label="Civic Engineering"
    )
    project = ProjectFactory()
    ContributionRecordFactory(
        contributor=user,
        project=project,
        contribution_type=engineering,
        status=VerificationStatus.ACCEPTED,
    )
    ContributionRecordFactory(
        contributor=user,
        project=project,
        contribution_type=engineering,
        status=VerificationStatus.CANDIDATE,
    )

    active_badge = BadgeFactory(name="Civic First Patch")
    BadgeAwardFactory(badge=active_badge, recipient=user, status=AwardStatus.ACTIVE)
    revoked_badge = BadgeFactory(name="Civic Revoked Badge")
    BadgeAwardFactory(badge=revoked_badge, recipient=user, status=AwardStatus.REVOKED)

    return {
        "owned_open": owned_open,
        "owned_completed": owned_completed,
        "other_project": other_project,
        "joined": joined,
        "declined_project": declined_project,
        "published": published,
        "draft": draft,
        "active_badge": active_badge,
        "revoked_badge": revoked_badge,
    }


def public_profile_url(user):
    return reverse("accounts:public_profile", kwargs={"username": user.username})


@pytest.mark.integration
def test_mem005_i1_public_profile_renders_separate_public_sections(client):
    """MEM-005-I1: the public profile renders projects, blogs, verified contributions, and
    badges in separate sections using only owned/public items."""
    user = UserFactory(username="portfolio-member")
    MemberProfileFactory(user=user)
    made = build_portfolio(user)

    response = client.get(public_profile_url(user))
    content = response.content.decode()

    assert response.status_code == 200
    assert 'id="projects-heading"' in content
    assert 'id="blogs-heading"' in content
    assert 'id="contributions-heading"' in content
    assert 'id="badges-heading"' in content
    assert f"/en/projects/{made['owned_open'].slug}/" in content
    assert f"/en/projects/{made['owned_completed'].slug}/" in content
    assert f"/en/projects/{made['joined'].slug}/" in content
    assert made["published"].title in content
    assert made["published"].canonical_url in content
    assert 'rel="noopener noreferrer"' in content
    assert "Civic Engineering" in content
    assert "1 verified contribution" in content
    assert made["active_badge"].name in content

    assert made["other_project"].slug not in content
    assert made["declined_project"].slug not in content
    assert made["draft"].title not in content
    assert made["revoked_badge"].name not in content


@pytest.mark.unit
def test_mem005_u1_payload_sections_exclude_nonpublic_and_unverified_items():
    """MEM-005-U1: payload querysets separate projects, blogs, verified contributions, badges."""
    from apps.accounts.services import public_profile_payload

    user = UserFactory()
    profile = MemberProfileFactory(user=user)
    made = build_portfolio(user)

    payload = public_profile_payload(profile)

    assert {row["slug"] for row in payload["projects"]} == {
        made["owned_open"].slug,
        made["owned_completed"].slug,
        made["joined"].slug,
    }
    assert [row["title"] for row in payload["blogs"]] == [made["published"].title]
    assert payload["contributions"] == [{"label": "Civic Engineering", "count": 1}]
    assert [row["name"] for row in payload["badges"]] == [made["active_badge"].name]


@pytest.mark.unit
def test_mem005_native_blog_posts_link_to_the_local_reading_view():
    """MEM-005/BLG-002: native posts in a public portfolio never produce an empty link."""
    from apps.accounts.services import public_profile_payload

    user = UserFactory(username="native-writer")
    profile = MemberProfileFactory(user=user)
    post = BlogPostFactory(
        author=user,
        status=BlogStatus.PUBLISHED,
        post_type=BlogPostType.NATIVE,
        canonical_url="",
        content_markdown="# Native post",
        content_rendered="<h1>Native post</h1>",
    )

    payload = public_profile_payload(profile)

    assert payload["blogs"] == [
        {
            "title": post.title,
            "url": reverse("blogs:detail", kwargs={"post_id": post.pk}),
            "published_at": post.published_at,
            "external": False,
        }
    ]


@pytest.mark.integration
def test_mem005_i1_portfolio_sections_keep_field_visibility_fail_closed(client):
    """MEM-003/MEM-005: portfolio sections render while absent visibility config hides
    links and skills; explicit public config reveals them."""
    user = UserFactory(username="failclosed-member")
    profile = MemberProfileFactory(user=user)
    build_portfolio(user)
    MemberLinkFactory(user=user, url="https://github.com/hidden", is_public=True)

    response = client.get(public_profile_url(user))
    payload = response.context["payload"]

    assert payload["links"] == []
    assert payload["skills"] == []
    assert b"https://github.com/hidden" not in response.content

    profile.field_visibility = {"links": Visibility.PUBLIC, "skills": Visibility.PUBLIC}
    profile.save()

    revealed = client.get(public_profile_url(user))

    assert [row["url"] for row in revealed.context["payload"]["links"]] == [
        "https://github.com/hidden"
    ]


@pytest.mark.integration
def test_mem005_i1_public_profile_query_count_is_constant_per_section_size(client):
    """MEM-005-I1: portfolio sections stay N+1-free as every section grows."""
    user = UserFactory(username="scaling-member")
    MemberProfileFactory(user=user)
    build_portfolio(user)
    for index in range(3):
        PersonalProjectFactory(
            owner=user, status=ProjectStatus.OPEN_FOR_CONTRIBUTION, slug=f"scale-p-{index}"
        )
        BlogPostFactory(author=user, status=BlogStatus.PUBLISHED, title=f"Scale post {index}")
        BadgeAwardFactory(
            badge=BadgeFactory(name=f"Scale badge {index}"),
            recipient=user,
            status=AwardStatus.ACTIVE,
        )
    type_a = TaxonomyTermFactory(vocabulary=TermVocabulary.CONTRIBUTION_TYPE, label="Scale Type A")
    type_b = TaxonomyTermFactory(vocabulary=TermVocabulary.CONTRIBUTION_TYPE, label="Scale Type B")
    project = ProjectFactory()
    for term in (type_a, type_b):
        for _ in range(2):
            ContributionRecordFactory(
                contributor=user,
                project=project,
                contribution_type=term,
                status=VerificationStatus.ACCEPTED,
            )

    url = public_profile_url(user)
    warm = client.get(url)
    assert warm.status_code == 200
    with CaptureQueriesContext(connection) as context:
        response = client.get(url)

    assert response.status_code == 200
    assert len(context) <= 8
