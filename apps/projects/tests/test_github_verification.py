import pytest
from django.test import Client
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.github_sync.tests.factories import GithubConnectionFactory
from apps.projects.enums import OwnershipVerificationStatus
from apps.projects.services import parse_github_repo_slug
from apps.projects.tests.factories import PersonalProjectFactory, UserFactory

pytestmark = pytest.mark.django_db


def matching_fetcher(login):
    def fetch(repo_slug):
        return {"owner": {"login": login}}

    return fetch


def failing_fetcher(repo_slug):
    raise RuntimeError("github api unavailable: token required for rate limits")


@pytest.mark.unit
@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://github.com/owner/repo", "owner/repo"),
        ("https://github.com/owner/repo/tree/main", "owner/repo"),
        ("http://github.com/owner/repo.git", "owner/repo"),
        ("https://www.github.com/owner/repo", "owner/repo"),
        ("https://gitlab.com/owner/repo", None),
        ("https://github.com/owner", None),
        ("not a url", None),
        ("", None),
    ],
)
def test_parse_github_repo_slug_handles_common_repository_urls(url, expected):
    """PPR-004: only GitHub repository URLs resolve to an owner/repo slug."""
    assert parse_github_repo_slug(url) == expected


@pytest.mark.integration
def test_matching_repo_owner_sets_verified_github_with_audit():
    """PPR-004: a public API owner match records VERIFIED_GITHUB with an audit row."""
    owner = UserFactory()
    project = PersonalProjectFactory(
        owner=owner, repository_url="https://github.com/ghmember42/community-widget"
    )
    GithubConnectionFactory(user=owner, login="GHMember42")

    status = request_verification(owner, project, matching_fetcher("ghmember42"))

    project.refresh_from_db()
    assert status == OwnershipVerificationStatus.VERIFIED_GITHUB
    assert project.ownership_verification == OwnershipVerificationStatus.VERIFIED_GITHUB
    assert AuditEvent.objects.filter(
        action="project.github_verified", object_id=str(project.pk)
    ).exists()


def request_verification(owner, project, fetcher):
    from apps.projects.services import request_github_ownership_verification

    return request_github_ownership_verification(owner, project, fetcher=fetcher)


@pytest.mark.integration
def test_owner_mismatch_keeps_unverified_with_audited_note():
    """PPR-004: a repository owned by someone else stays UNVERIFIED with an audit note."""
    owner = UserFactory()
    project = PersonalProjectFactory(
        owner=owner, repository_url="https://github.com/someoneelse/community-widget"
    )
    GithubConnectionFactory(user=owner, login="ghmember42")

    status = request_verification(owner, project, matching_fetcher("someoneelse"))

    project.refresh_from_db()
    assert status == OwnershipVerificationStatus.UNVERIFIED
    assert project.ownership_verification == OwnershipVerificationStatus.UNVERIFIED
    event = AuditEvent.objects.get(action="project.github_verify_failed", object_id=str(project.pk))
    assert "does not match" in (event.after or {}).get("note", "")


@pytest.mark.integration
def test_fetcher_failure_falls_back_to_unverified_without_crashing():
    """PPR-004: an unavailable GitHub API (e.g. token required) fails gracefully to UNVERIFIED."""
    owner = UserFactory()
    project = PersonalProjectFactory(
        owner=owner, repository_url="https://github.com/ghmember42/community-widget"
    )
    GithubConnectionFactory(user=owner, login="ghmember42")

    status = request_verification(owner, project, failing_fetcher)

    project.refresh_from_db()
    assert status == OwnershipVerificationStatus.UNVERIFIED
    assert project.ownership_verification == OwnershipVerificationStatus.UNVERIFIED
    event = AuditEvent.objects.get(action="project.github_verify_failed", object_id=str(project.pk))
    assert (event.after or {}).get("note")


@pytest.mark.integration
def test_missing_github_connection_fails_gracefully_with_audit_note():
    """PPR-004: no connected GitHub account means verification cannot match; stays UNVERIFIED."""
    owner = UserFactory()
    project = PersonalProjectFactory(
        owner=owner, repository_url="https://github.com/ghmember42/community-widget"
    )

    status = request_verification(owner, project, matching_fetcher("ghmember42"))

    project.refresh_from_db()
    assert status == OwnershipVerificationStatus.UNVERIFIED
    event = AuditEvent.objects.get(action="project.github_verify_failed", object_id=str(project.pk))
    assert "no connected" in (event.after or {}).get("note", "")


@pytest.mark.integration
def test_verification_requires_owner_and_a_github_repository_url():
    """PPR-004/AUTH-006: only the owner may verify, and a GitHub repo URL is required."""
    owner = UserFactory()
    project = PersonalProjectFactory(owner=owner, repository_url="")
    GithubConnectionFactory(user=owner, login="ghmember42")

    from apps.projects.services import (
        ProjectAuthorizationError,
        ProjectLifecycleError,
        request_github_ownership_verification,
    )

    with pytest.raises(ProjectLifecycleError):
        request_github_ownership_verification(owner, project, fetcher=matching_fetcher("x"))

    project.repository_url = "https://github.com/ghmember42/community-widget"
    project.save(update_fields=["repository_url"])
    with pytest.raises(ProjectAuthorizationError):
        request_github_ownership_verification(
            UserFactory(), project, fetcher=matching_fetcher("ghmember42")
        )


@pytest.mark.integration
def test_verify_route_is_owner_scoped_and_post_only(client):
    """PPR-004/AUTH-006: the verification route is POST-only and scoped to the listing owner."""
    owner = UserFactory()
    project = PersonalProjectFactory(
        owner=owner, repository_url="https://github.com/ghmember42/community-widget"
    )
    GithubConnectionFactory(user=owner, login="ghmember42")
    url = reverse("projects:community_verify_github", kwargs={"slug": project.slug})

    assert client.get(url).status_code == 302

    client.force_login(owner)
    assert client.get(url).status_code == 405

    from apps.projects import services

    original = services._fetch_github_repo_via_api
    services._fetch_github_repo_via_api = matching_fetcher("ghmember42")
    try:
        response = client.post(url)
    finally:
        services._fetch_github_repo_via_api = original

    assert response.status_code == 302
    project.refresh_from_db()
    assert project.ownership_verification == OwnershipVerificationStatus.VERIFIED_GITHUB

    foreign_client = Client()
    foreign_client.force_login(UserFactory())
    assert foreign_client.post(url).status_code == 404


@pytest.mark.integration
def test_community_detail_shows_verification_status(client):
    """PPR-004: the owner's project page shows the recorded verification status."""
    owner = UserFactory()
    project = PersonalProjectFactory(
        owner=owner,
        repository_url="https://github.com/ghmember42/community-widget",
        ownership_verification=OwnershipVerificationStatus.VERIFIED_GITHUB,
    )
    client.force_login(owner)

    response = client.get(reverse("projects:community_detail", kwargs={"slug": project.slug}))

    assert response.status_code == 200
    assert b"Verified via GitHub" in response.content
    assert b"Verify GitHub ownership" in response.content


@pytest.mark.integration
def test_verify_route_without_repository_url_renders_error():
    """PPR-004: verifying a listing without a GitHub repository URL fails explicitly."""
    owner = UserFactory()
    project = PersonalProjectFactory(owner=owner, repository_url="")
    client = Client()
    client.force_login(owner)

    response = client.post(
        reverse("projects:community_verify_github", kwargs={"slug": project.slug})
    )

    assert response.status_code == 400
    project.refresh_from_db()
    assert project.ownership_verification == OwnershipVerificationStatus.UNVERIFIED
