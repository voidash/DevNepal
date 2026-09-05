import pytest
from django.urls import reverse
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.ministries.tests.factories import MinistryPublisherFactory
from apps.projects.enums import ProjectStatus, UpdateKind
from apps.projects.models import ProjectUpdate
from apps.projects.tests.factories import ProjectUpdateFactory, make_publishable

pytestmark = pytest.mark.django_db


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


def open_project(**kwargs):
    project = make_publishable(**kwargs)
    project.status = ProjectStatus.OPEN_FOR_CONTRIBUTION
    project.save(update_fields=["status"])
    return project


def manage_url(project):
    return reverse("projects:authoring_manage", kwargs={"slug": project.slug})


@pytest.mark.integration
def test_publisher_posts_progress_update_through_manage_route(client):
    """GOV-009: an MFA-verified publisher posts a progress update from authoring manage."""
    project = open_project()
    verify_mfa(client, project.owner)

    response = client.post(
        manage_url(project),
        {
            "action": "update",
            "title": "Sprint 4 done",
            "body": "Search shipped to the pilot ministry.",
            "kind": UpdateKind.PROGRESS,
            "link": "",
        },
    )

    assert response.status_code == 302
    update = ProjectUpdate.objects.get(project=project)
    assert update.title == "Sprint 4 done"
    assert update.kind == UpdateKind.PROGRESS
    assert update.created_by == project.owner
    project.refresh_from_db()
    assert project.last_maintainer_activity_at is not None


@pytest.mark.integration
def test_publisher_posts_release_link_and_milestone_updates(client):
    """GOV-009: release/result links and milestone status ride the same update route."""
    project = open_project()
    verify_mfa(client, project.owner)

    release_response = client.post(
        manage_url(project),
        {
            "action": "update",
            "title": "v1 released",
            "body": "First public release.",
            "kind": UpdateKind.RELEASE,
            "link": "https://github.com/moit/repo/releases/v1.0",
        },
    )
    milestone_response = client.post(
        manage_url(project),
        {
            "action": "update",
            "title": "Pilot milestone achieved",
            "body": "The pilot ministry signed off.",
            "kind": UpdateKind.MILESTONE,
            "link": "",
        },
    )

    assert release_response.status_code == 302
    assert milestone_response.status_code == 302
    release = ProjectUpdate.objects.get(project=project, kind=UpdateKind.RELEASE)
    assert release.link == "https://github.com/moit/repo/releases/v1.0"
    assert ProjectUpdate.objects.filter(project=project, kind=UpdateKind.MILESTONE).exists()


@pytest.mark.integration
def test_update_route_rejects_invalid_and_unknown_actions(client):
    """GOV-009: missing required fields and unknown actions are rejected without side effects."""
    project = open_project()
    verify_mfa(client, project.owner)

    missing_title = client.post(
        manage_url(project),
        {"action": "update", "title": "", "body": "No title.", "kind": UpdateKind.PROGRESS},
    )
    unknown_action = client.post(manage_url(project), {"action": "nonsense"})

    assert missing_title.status_code == 400
    assert unknown_action.status_code == 400
    assert not ProjectUpdate.objects.filter(project=project).exists()


@pytest.mark.integration
def test_update_route_is_mfa_gated_and_ministry_scoped(client):
    """GOV-009/AUTH-006: unverified sessions are redirected and foreign publishers get 404."""
    project = open_project()
    client.force_login(project.owner)

    unverified = client.post(
        manage_url(project),
        {"action": "update", "title": "No MFA", "body": "Should not pass."},
    )
    assert unverified.status_code == 302
    assert unverified.url == reverse("accounts:mfa_setup")

    foreign_publisher = MinistryPublisherFactory()
    verify_mfa(client, foreign_publisher.user)
    assert (
        client.post(
            manage_url(project),
            {"action": "update", "title": "Foreign", "body": "Nope.", "kind": UpdateKind.PROGRESS},
        ).status_code
        == 404
    )
    assert not ProjectUpdate.objects.filter(project=project).exists()


@pytest.mark.integration
def test_public_updates_route_renders_timeline_with_public_fields_only(
    client, django_assert_max_num_queries
):
    """GOV-009: the public updates route shows a timeline of public fields without N+1 queries."""
    project = open_project()
    update = ProjectUpdateFactory(
        project=project,
        title="Release v1",
        body="First public release is out.",
        kind=UpdateKind.RELEASE,
        link="https://github.com/moit/repo/releases/v1.0",
    )

    with django_assert_max_num_queries(60):
        response = client.get(reverse("projects:updates", kwargs={"slug": project.slug}))

    assert response.status_code == 200
    content = response.content
    assert b"Release v1" in content
    assert b"First public release is out." in content
    assert b"releases/v1.0" in content
    assert update.created_by.username.encode() not in content


@pytest.mark.integration
def test_public_detail_keeps_updates_timeline_off_the_minimal_surface(client):
    """GOV-009/DSC-009: updates remain stored but do not expand the issue-first demo."""
    project = open_project()
    ProjectUpdateFactory(
        project=project,
        title="Release v1",
        body="First public release is out.",
        kind=UpdateKind.RELEASE,
    )

    response = client.get(reverse("projects:detail", kwargs={"slug": project.slug}))

    assert response.status_code == 200
    content = response.content
    updates_path = reverse("projects:updates", kwargs={"slug": project.slug}).encode()
    assert updates_path not in content
    assert b"Release v1" not in content
    assert b"Last maintainer activity" in content
