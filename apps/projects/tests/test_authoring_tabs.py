import pytest
from django.urls import reverse
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.accounts.tests.factories import UserFactory
from apps.ministries.tests.factories import MinistryPublisherFactory
from apps.projects.enums import AttachmentKind, ProjectStatus, UpdateKind
from apps.projects.tests.factories import (
    PersonalProjectFactory,
    ProjectAttachmentFactory,
    ProjectScreeningQuestionFactory,
    ProjectUpdateFactory,
    SuperAdminFactory,
    make_publishable,
)

pytestmark = pytest.mark.django_db

AUTHORING_TABS = (
    ("authoring_detail", "overview-heading"),
    ("authoring_readiness", "readiness-heading"),
    ("authoring_attachment", "attachments-heading"),
    ("authoring_updates", "updates-heading"),
    ("authoring_questions", "questions-heading"),
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


@pytest.mark.integration
def test_authoring_tab_routes_render_only_their_section_for_the_owning_publisher(client):
    """GOV-004/GOV-005: each authoring tab is a real route rendering only its own section."""
    project = make_publishable()
    verify_mfa(client, project.owner)

    for route_name, heading_id in AUTHORING_TABS:
        path = reverse(f"projects:{route_name}", kwargs={"slug": project.slug})
        response = client.get(path)

        assert response.status_code == 200, route_name
        content = response.content.decode()
        assert f'<h2 id="{heading_id}">' in content, route_name
        assert content.count('aria-current="page"') == 1, route_name
        assert f'aria-current="page" href="{path}"' in content, route_name

    overview = client.get(
        reverse("projects:authoring_detail", kwargs={"slug": project.slug})
    ).content.decode()
    assert '<h2 id="workflow-heading">' in overview
    for route_name, _heading_id in AUTHORING_TABS[1:]:
        content = client.get(
            reverse(f"projects:{route_name}", kwargs={"slug": project.slug})
        ).content.decode()
        assert '<h2 id="overview-heading">' not in content, route_name
        assert '<h2 id="workflow-heading">' not in content, route_name


@pytest.mark.integration
def test_authoring_tab_routes_require_mfa_and_ministry_membership(client):
    """AUTH-005/AUTH-006: tab routes are MFA-gated and ministry-scoped like the overview."""
    project = make_publishable()
    foreign_publisher = MinistryPublisherFactory()

    client.force_login(foreign_publisher.user)
    for route_name, _ in AUTHORING_TABS:
        response = client.get(reverse(f"projects:{route_name}", kwargs={"slug": project.slug}))
        assert response.status_code == 302, route_name
        assert response.url == reverse("accounts:mfa_setup"), route_name

    verify_mfa(client, foreign_publisher.user)
    for route_name, _ in AUTHORING_TABS:
        response = client.get(reverse(f"projects:{route_name}", kwargs={"slug": project.slug}))
        assert response.status_code == 404, route_name


@pytest.mark.integration
def test_authoring_tab_routes_redirect_anonymous_visitors_to_login(client):
    """AUTH-001: anonymous visitors never see authoring tabs, only the login redirect."""
    project = make_publishable()

    for route_name, _ in AUTHORING_TABS:
        response = client.get(reverse(f"projects:{route_name}", kwargs={"slug": project.slug}))
        assert response.status_code == 302, route_name
        assert reverse("accounts:login") in response.url, route_name


@pytest.mark.integration
def test_authoring_tabs_carry_real_counters_on_every_tab(client):
    """A8/GOV-004: tab counters show real record counts on every authoring tab."""
    project = make_publishable()
    ProjectAttachmentFactory(project=project, kind=AttachmentKind.REQUIREMENTS)
    ProjectAttachmentFactory(project=project, kind=AttachmentKind.REQUIREMENTS)
    ProjectUpdateFactory(project=project, kind=UpdateKind.PROGRESS)
    ProjectUpdateFactory(project=project, kind=UpdateKind.MILESTONE)
    ProjectUpdateFactory(project=project, kind=UpdateKind.RELEASE)
    ProjectScreeningQuestionFactory(project=project)
    ProjectScreeningQuestionFactory(project=project)
    ProjectScreeningQuestionFactory(project=project)
    ProjectScreeningQuestionFactory(project=project)
    verify_mfa(client, project.owner)

    for route_name, _ in AUTHORING_TABS:
        content = client.get(
            reverse(f"projects:{route_name}", kwargs={"slug": project.slug})
        ).content.decode()
        assert '<span class="Counter">0</span>' in content, route_name
        assert '<span class="Counter">2</span>' in content, route_name
        assert '<span class="Counter">3</span>' in content, route_name
        assert '<span class="Counter">4</span>' in content, route_name


@pytest.mark.integration
def test_attachment_route_renders_the_tab_on_get_and_uploads_on_post(client):
    """GOV-003/GOV-004: the attachments route serves the tab via GET and uploads via POST."""
    project = make_publishable()
    verify_mfa(client, project.owner)
    url = reverse("projects:authoring_attachment", kwargs={"slug": project.slug})

    tab = client.get(url)
    assert tab.status_code == 200
    content = tab.content.decode()
    assert '<h2 id="attachments-heading">' in content
    assert f'aria-current="page" href="{url}"' in content


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
def test_manage_errors_rerender_the_tab_that_posted(client):
    """GOV-004: a failed update POST returns to the updates tab with the error visible."""
    project = make_publishable()
    verify_mfa(client, project.owner)
    manage_url = reverse("projects:authoring_manage", kwargs={"slug": project.slug})

    response = client.post(manage_url, {"action": "update", "title": "", "body": ""})

    assert response.status_code == 400
    content = response.content.decode()
    assert '<h2 id="updates-heading">' in content
    assert '<h2 id="overview-heading">' not in content


@pytest.mark.integration
def test_workflow_errors_rerender_the_overview_tab(client):
    """GOV-005/AUTH-006: a refused lifecycle action returns to the overview workflow form."""
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
    content = response.content.decode()
    assert '<h2 id="workflow-heading">' in content
    assert '<h2 id="updates-heading">' not in content


@pytest.mark.integration
def test_authoring_tabs_no_longer_use_page_anchors(client):
    """GOV-004: legacy #anchor links are gone; every tab is a real resolvable route."""
    project = make_publishable()
    verify_mfa(client, project.owner)

    response = client.get(reverse("projects:authoring_detail", kwargs={"slug": project.slug}))

    assert response.status_code == 200
    content = response.content.decode()
    assert 'href="#readiness"' not in content
    assert 'href="#attachments"' not in content
    assert 'href="#updates"' not in content
    assert 'href="#questions"' not in content
    for route_name, _ in AUTHORING_TABS:
        path = reverse(f"projects:{route_name}", kwargs={"slug": project.slug})
        assert f'href="{path}"' in content, route_name


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
def test_public_detail_tabs_link_to_the_updates_route(client):
    """DSC-009: the public detail header links overview and updates as real routes."""
    project = PersonalProjectFactory(status=ProjectStatus.OPEN_FOR_CONTRIBUTION)
    updates_path = reverse("projects:updates", kwargs={"slug": project.slug})
    detail_path = reverse("projects:detail", kwargs={"slug": project.slug})

    response = client.get(detail_path)

    assert response.status_code == 200
    content = response.content.decode()
    assert updates_path in content
    assert f'aria-current="page" href="{detail_path}"' in content
    assert 'href="#updates"' not in content
