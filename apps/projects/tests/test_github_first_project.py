import pytest
from django.urls import reverse

from apps.github_sync.models import (
    GithubIssueSnapshot,
    GithubPullRequestSnapshot,
    GithubRepositoryContributor,
)
from apps.github_sync.tests.factories import RepositoryConnectionFactory
from apps.projects.enums import ProjectStatus
from apps.projects.tests.factories import ProjectFactory, ProjectVersionFactory

pytestmark = [pytest.mark.django_db]


def public_project():
    project = ProjectFactory(
        status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
        repository_url="https://github.com/voidash/civic-help-directory",
    )
    version = ProjectVersionFactory(project=project)
    project.current_version = version
    project.save(update_fields=["current_version"])
    repository = RepositoryConnectionFactory(
        project=project,
        full_name="voidash/civic-help-directory",
        is_public=True,
    )
    return project, repository


def test_dsc_005_project_shows_synced_github_issues_prs_and_contributors(client):
    """DSC-005/GIT-010: the project page is a concise view of public GitHub work."""
    project, repository = public_project()
    issue = GithubIssueSnapshot.objects.create(
        repository=repository,
        github_issue_id=7,
        number=7,
        title="Add Nepali eligibility text",
        body="Translate the eligibility guidance.",
        state="open",
        url="https://github.com/voidash/civic-help-directory/issues/7",
        author_login="voidash",
    )
    GithubPullRequestSnapshot.objects.create(
        repository=repository,
        github_pull_request_id=10,
        number=10,
        title="Document keyboard-only contribution workflow",
        state="open",
        url="https://github.com/voidash/civic-help-directory/pull/10",
        author_login="voidash",
    )
    GithubRepositoryContributor.objects.create(
        repository=repository,
        github_user_id=1,
        login="voidash",
        profile_url="https://github.com/voidash",
        contributions=9,
    )

    response = client.get(reverse("projects:detail", kwargs={"slug": project.slug}))

    content = response.content.decode()
    assert response.status_code == 200
    assert issue.title in content
    assert (
        reverse("projects:github_issue", kwargs={"slug": project.slug, "number": issue.number})
        in content
    )
    assert "Document keyboard-only contribution workflow" in content
    assert "voidash" in content


def test_dsc_005_visitor_reads_full_synced_issue_before_starting_on_github(client):
    """DSC-005/GIT-010: visitors can read a public issue snapshot before leaving for GitHub."""
    project, repository = public_project()
    issue = GithubIssueSnapshot.objects.create(
        repository=repository,
        github_issue_id=7,
        number=7,
        title="Add Nepali eligibility text",
        body="Translate every public eligibility rule and preserve the source links.",
        state="open",
        comments_count=2,
        url="https://github.com/voidash/civic-help-directory/issues/7",
        author_login="voidash",
    )

    response = client.get(
        reverse("projects:github_issue", kwargs={"slug": project.slug, "number": 7})
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert issue.body in content
    assert issue.url in content
    assert "Start contributing on GitHub" in content
