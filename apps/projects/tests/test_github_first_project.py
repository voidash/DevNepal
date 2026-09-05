from pathlib import Path

import pytest
from django.conf import settings
from django.test import override_settings
from django.urls import reverse

from apps.github_sync.models import (
    GithubIssueSnapshot,
    GithubPullRequestSnapshot,
    GithubRepositoryContributor,
)
from apps.github_sync.tests.factories import RepositoryConnectionFactory
from apps.ministries.tests.factories import MinistryPublisherFactory
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
    assert reverse("github_sync_public:public_profile", args=["voidash"]) in content


def test_dsc_005_project_header_sits_close_under_the_product_nav():
    """DSC-005: the project sheet starts close under the product header."""
    css = (Path(settings.BASE_DIR) / "static/src/devnepal.css").read_text()
    header = ".dn-page-header:has(.dn-project-hero)"

    assert f"{header} {{ padding-top: var(--space-4); }}" in css
    assert f"{header} .dn-breadcrumbs {{ padding: var(--space-2) 0 var(--space-3); }}" in css


def test_dsc_005_project_people_show_github_avatars_not_initials(client):
    """DSC-005/GIT-010: repository people use the public GitHub avatar image."""
    project, repository = public_project()
    GithubRepositoryContributor.objects.create(
        repository=repository,
        github_user_id=700000,
        login="voidash",
        avatar_url="https://avatars.githubusercontent.com/u/700000?v=4",
        profile_url="https://github.com/voidash",
        contributions=41,
    )
    GithubRepositoryContributor.objects.create(
        repository=repository,
        github_user_id=42,
        login="aarati-shrestha",
        profile_url="https://github.com/aarati-shrestha",
        contributions=9,
    )

    response = client.get(reverse("projects:detail", kwargs={"slug": project.slug}))
    section = (
        response.content.split(b'aria-labelledby="contributors-heading"', 1)[1]
        .split(b"</section>", 1)[0]
        .decode()
    )

    assert response.status_code == 200
    assert 'src="https://avatars.githubusercontent.com/voidash?s=80&v=4"' in section
    assert 'src="https://avatars.githubusercontent.com/aarati-shrestha?s=80&v=4"' in section
    assert "avatars.githubusercontent.com/u/700000" not in section
    assert 'class="dn-github-avatar"' not in section


def test_dsc_005_visitor_reads_full_synced_issue_before_starting_on_github(client):
    """DSC-005/GIT-010: visitors can read a public issue snapshot before leaving for GitHub."""
    project, repository = public_project()
    issue = GithubIssueSnapshot.objects.create(
        repository=repository,
        github_issue_id=7,
        number=7,
        title="Add Nepali eligibility text",
        body=(
            "## Goal\n\nTranslate every public eligibility rule.\n\n"
            "## Acceptance criteria\n\n- Preserve source links.\n- Keep JSON valid."
        ),
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
    assert "<h2>Goal</h2>" in content
    assert "<h2>Acceptance criteria</h2>" in content
    assert "<ul>" in content
    assert "<li>Preserve source links.</li>" in content
    assert "## Goal" not in content
    assert issue.url in content
    assert "Start contributing on GitHub" in content


@override_settings(PRIVILEGED_MFA_BYPASS=True)
def test_gov_004_publisher_workspace_shows_the_connected_github_repository_activity(client):
    """GOV-004/GIT-010: a ministry sees GitHub issues, pull requests and contributors in place."""
    assignment = MinistryPublisherFactory()
    project = ProjectFactory(
        owner=assignment.user,
        ministry=assignment.ministry,
        status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
    )
    repository = RepositoryConnectionFactory(
        project=project,
        full_name="voidash/civic-help-directory",
        is_public=True,
        deactivated_at=None,
    )
    GithubIssueSnapshot.objects.create(
        repository=repository,
        github_issue_id=7,
        number=7,
        title="Add Nepali eligibility text",
        state="open",
        url="https://github.com/voidash/civic-help-directory/issues/7",
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
    client.force_login(assignment.user)

    response = client.get(reverse("projects:authoring_detail", args=[project.slug]))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Add Nepali eligibility text" in content
    assert "Document keyboard-only contribution workflow" in content
    assert reverse("github_sync_public:public_profile", args=["voidash"]) in content
    assert reverse("projects:detail", args=[project.slug]) in content
    assert "Review history" not in content
    assert "Assign maintainer" not in content


@override_settings(
    PRIVILEGED_MFA_BYPASS=True,
    GITHUB_APP_ID="123",
    GITHUB_APP_PRIVATE_KEY="configured-for-template-test",
)
def test_gov_004_new_project_workspace_links_to_repository_connection(client):
    """GOV-004/GIT-003: a new ministry project has an actionable repository next step."""
    assignment = MinistryPublisherFactory()
    project = ProjectFactory(
        owner=assignment.user,
        ministry=assignment.ministry,
        status=ProjectStatus.DRAFT,
    )
    client.force_login(assignment.user)

    response = client.get(reverse("projects:authoring_detail", args=[project.slug]))

    expected = f"{reverse('github_sync:connect_repository')}?project_id={project.pk}"
    assert response.status_code == 200
    assert f'href="{expected}"' in response.content.decode()
