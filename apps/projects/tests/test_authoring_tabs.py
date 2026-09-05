import pytest
from django.urls import reverse
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.accounts.tests.factories import UserFactory
from apps.github_sync.models import (
    GithubIssueSnapshot,
    GithubPullRequestSnapshot,
    GithubRepositoryContributor,
)
from apps.ministries.tests.factories import MinistryPublisherFactory
from apps.projects.enums import AttachmentKind, ProjectStatus, UpdateKind
from apps.projects.tests.factories import (
    PersonalProjectFactory,
    ProjectUpdateFactory,
    SuperAdminFactory,
    make_publishable,
)

pytestmark = pytest.mark.django_db

AUTHORING_ROUTES = (
    "authoring_detail",
    "authoring_readiness",
    "authoring_attachment",
    "authoring_updates",
    "authoring_questions",
)


def verify_mfa(client, user):
    client.force_login(user)
    setup_url = reverse("accounts:mfa_setup")
    assert client.get(setup_url).status_code == 200
    device = TOTPDevice.objects.get(user=user)
    device.last_t = -1
    device.save(update_fields=["last_t"])
    token = totp(
        device.bin_key,
        step=device.step,
        t0=device.t0,
        digits=device.digits,
        drift=device.drift,
    )
    response = client.post(setup_url, {"token": token})
    assert response.status_code == 302


def add_github_activity(project, *, issue_count=1, pull_request_count=1):
    repository = project.repository_connections.get()
    for number in range(1, issue_count + 1):
        GithubIssueSnapshot.objects.create(
            repository=repository,
            github_issue_id=700 + number,
            number=number,
            title=f"Accessibility task {number}",
            state="open",
            url=f"https://github.com/moit/service-directory/issues/{number}",
        )
    for number in range(1, pull_request_count + 1):
        GithubPullRequestSnapshot.objects.create(
            repository=repository,
            github_pull_request_id=800 + number,
            number=number,
            title=f"Accessibility pull request {number}",
            state="open",
            url=f"https://github.com/moit/service-directory/pull/{number}",
            author_login="voidash",
        )
    GithubRepositoryContributor.objects.create(
        repository=repository,
        github_user_id=900,
        login="voidash",
        profile_url="https://github.com/voidash",
        contributions=9,
    )


@pytest.mark.integration
def test_publisher_authoring_routes_render_the_github_first_workspace(client):
    """GOV-004/GIT-010: publisher routes retain access control while showing GitHub activity."""
    project = make_publishable()
    add_github_activity(project)
    verify_mfa(client, project.owner)

    for route_name in AUTHORING_ROUTES:
        path = reverse(f"projects:{route_name}", kwargs={"slug": project.slug})
        response = client.get(path)

        assert response.status_code == 200, route_name
        content = response.content.decode()
        assert "GitHub activity" in content, route_name
        assert "moit/service-directory" in content, route_name
        assert "Accessibility task 1" in content, route_name
        assert "Accessibility pull request 1" in content, route_name
        assert reverse("github_sync_public:public_profile", args=["voidash"]) in content, route_name
        assert "Project workflow" not in content, route_name
        assert "Review history" not in content, route_name


@pytest.mark.integration
def test_authoring_overview_exposes_repository_activity_without_user_oauth_binding(client):
    """GIT-003/GOV-007: publishers inspect repository activity without a user OAuth action."""
    project = make_publishable()
    repository = project.repository_connections.get()
    verify_mfa(client, project.owner)

    response = client.get(reverse("projects:authoring_detail", kwargs={"slug": project.slug}))

    assert response.status_code == 200
    content = response.content.decode()
    assert repository.full_name in content
    expected = f"{reverse('github_sync:connect_repository')}?project_id={project.pk}"
    assert f'href="{expected}"' not in content


@pytest.mark.integration
def test_authoring_tab_routes_require_mfa_and_ministry_membership(client):
    """AUTH-005/AUTH-006: tab routes are MFA-gated and ministry-scoped like the overview."""
    project = make_publishable()
    foreign_publisher = MinistryPublisherFactory()

    client.force_login(foreign_publisher.user)
    for route_name in AUTHORING_ROUTES:
        response = client.get(reverse(f"projects:{route_name}", kwargs={"slug": project.slug}))
        assert response.status_code == 302, route_name
        assert response.url == reverse("accounts:mfa_setup"), route_name

    verify_mfa(client, foreign_publisher.user)
    for route_name in AUTHORING_ROUTES:
        response = client.get(reverse(f"projects:{route_name}", kwargs={"slug": project.slug}))
        assert response.status_code == 404, route_name


@pytest.mark.integration
def test_authoring_tab_routes_redirect_anonymous_visitors_to_login(client):
    """AUTH-001: anonymous visitors never see authoring tabs, only the login redirect."""
    project = make_publishable()

    for route_name in AUTHORING_ROUTES:
        response = client.get(reverse(f"projects:{route_name}", kwargs={"slug": project.slug}))
        assert response.status_code == 302, route_name
        assert reverse("accounts:login") in response.url, route_name


@pytest.mark.integration
def test_publisher_workspace_carries_real_github_counters_on_every_route(client):
    """GOV-004/GIT-010: publisher routes retain synchronized issue and PR counts."""
    project = make_publishable()
    add_github_activity(project, issue_count=2, pull_request_count=3)
    verify_mfa(client, project.owner)

    for route_name in AUTHORING_ROUTES:
        content = client.get(
            reverse(f"projects:{route_name}", kwargs={"slug": project.slug})
        ).content.decode()
        assert '<span class="Counter">2</span>' in content, route_name
        assert '<span class="Counter">3</span>' in content, route_name
        assert "Repository contributors" in content, route_name
        assert "9 commits" in content, route_name


@pytest.mark.integration
def test_attachment_route_keeps_the_publisher_in_the_github_first_workspace(client):
    """GOV-003/GOV-004: legacy attachment routes do not restore attachment UI for publishers."""
    project = make_publishable()
    verify_mfa(client, project.owner)
    url = reverse("projects:authoring_attachment", kwargs={"slug": project.slug})

    response = client.get(url)

    assert response.status_code == 200
    content = response.content.decode()
    assert "GitHub activity" in content
    assert "Connected GitHub repository" in content
    assert "Upload attachment" not in content
    assert '<h2 id="attachments-heading">' not in content


@pytest.mark.integration
def test_attachment_upload_redirects_back_to_the_attachments_tab(client):
    """GOV-003: a successful upload returns the publisher to the attachments tab."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    project = make_publishable()
    verify_mfa(client, project.owner)
    url = reverse("projects:authoring_attachment", kwargs={"slug": project.slug})

    response = client.post(
        url,
        {
            "kind": AttachmentKind.PROPOSAL,
            "language": "en",
            "classification": "public",
            "file": SimpleUploadedFile("proposal.pdf", b"%PDF-1.4", content_type="application/pdf"),
        },
    )

    assert response.status_code == 302
    assert response.url == url


@pytest.mark.integration
def test_manage_errors_preserve_validation_without_restoring_legacy_publisher_forms(client):
    """GOV-004: legacy management validation survives without restoring removed publisher forms."""
    project = make_publishable()
    verify_mfa(client, project.owner)
    manage_url = reverse("projects:authoring_manage", kwargs={"slug": project.slug})

    response = client.post(manage_url, {"action": "update", "title": "", "body": ""})

    assert response.status_code == 400
    assert response.context["update_form"].errors
    content = response.content.decode()
    assert "GitHub activity" in content
    assert "Post update" not in content


@pytest.mark.integration
def test_workflow_errors_preserve_validation_without_restoring_legacy_publisher_forms(client):
    """GOV-005/AUTH-006: refused transitions stay validated without restored workflow UI."""
    project = make_publishable()
    super_admin = SuperAdminFactory()
    verify_mfa(client, project.owner)
    workflow_url = reverse("projects:authoring_workflow", kwargs={"slug": project.slug})
    assert client.post(workflow_url, {"action": "submit"}).status_code == 302
    verify_mfa(client, super_admin)
    assert client.post(workflow_url, {"action": "approve"}).status_code == 302
    assert client.post(workflow_url, {"action": "publish"}).status_code == 302
    verify_mfa(client, project.owner)
    assert client.post(workflow_url, {"action": "archive"}).status_code == 302
    project.refresh_from_db()
    assert project.status == ProjectStatus.ARCHIVED

    response = client.post(workflow_url, {"action": "restore"})

    assert response.status_code == 400
    assert response.context["workflow_form"].errors
    content = response.content.decode()
    assert "GitHub activity" in content
    assert "Next lifecycle action" not in content


@pytest.mark.integration
def test_publisher_workspace_omits_legacy_workflow_navigation(client):
    """GOV-004/GIT-010: publisher workspace exposes repository work, not legacy workflow tabs."""
    project = make_publishable()
    verify_mfa(client, project.owner)

    response = client.get(reverse("projects:authoring_detail", kwargs={"slug": project.slug}))

    assert response.status_code == 200
    content = response.content.decode()
    assert 'href="#readiness"' not in content
    assert 'href="#attachments"' not in content
    assert 'href="#updates"' not in content
    assert 'href="#questions"' not in content
    assert "GitHub activity" in content
    assert "Project workflow" not in content
    assert "Readiness" not in content
    assert "Attachments" not in content
    assert "Updates" not in content
    assert "Questions" not in content


@pytest.mark.integration
def test_public_updates_route_renders_the_timeline_without_author_details(client):
    """DSC-009: the public updates timeline shows public fields only, never the author."""
    project = PersonalProjectFactory(status=ProjectStatus.OPEN_FOR_CONTRIBUTION)
    author = UserFactory(username="update-author-official")
    ProjectUpdateFactory(
        project=project,
        title="Sprint shipped",
        body="The directory pilot is live.",
        kind=UpdateKind.RELEASE,
        created_by=author,
    )

    response = client.get(reverse("projects:updates", kwargs={"slug": project.slug}))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Sprint shipped" in content
    assert "The directory pilot is live." in content
    assert "update-author-official" not in content


@pytest.mark.integration
def test_public_updates_route_hides_non_public_projects(client):
    """GOV-011: drafts and other non-public projects 404 on the public updates route."""
    draft = make_publishable()
    assert client.get(reverse("projects:updates", kwargs={"slug": draft.slug})).status_code == 404


@pytest.mark.integration
def test_public_detail_keeps_updates_out_of_the_minimal_issue_first_surface(client):
    """DSC-009: a direct updates route can remain without expanding the demo surface."""
    project = PersonalProjectFactory(status=ProjectStatus.OPEN_FOR_CONTRIBUTION)
    updates_path = reverse("projects:updates", kwargs={"slug": project.slug})
    detail_path = reverse("projects:detail", kwargs={"slug": project.slug})

    response = client.get(detail_path)

    assert response.status_code == 200
    content = response.content.decode()
    assert updates_path not in content
    assert f'aria-current="page" href="{detail_path}"' not in content
    assert 'href="#updates"' not in content
