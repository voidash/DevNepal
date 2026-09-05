from pathlib import Path

import pytest
from django.conf import settings
from django.urls import reverse
from django.utils import translation
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.github_sync.tests.factories import RepositoryConnectionFactory
from apps.ministries.tests.factories import MinistryPublisherFactory
from apps.projects.models import Project
from apps.projects.tests.factories import ProjectFactory

pytestmark = pytest.mark.django_db


def _verify_mfa(client, user):
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
    assert client.post(setup_url, {"token": token}).status_code == 302


@pytest.mark.integration
def test_demo_fill_control_is_create_only_and_carries_civic_help_directory_data(client):
    """GOV-001/GOV-002: an authorized publisher can opt into unsaved real-repository demo data."""
    assignment = MinistryPublisherFactory()
    _verify_mfa(client, assignment.user)
    project = ProjectFactory(owner=assignment.user, ministry=assignment.ministry)

    create_response = client.get(reverse("projects:authoring_create"))
    edit_response = client.get(reverse("projects:authoring_edit", kwargs={"slug": project.slug}))

    create_content = create_response.content.decode()
    edit_content = edit_response.content.decode()
    assert create_response.status_code == 200
    assert 'id="fill-demo-details"' in create_content
    assert 'type="button"' in create_content
    assert 'id="authoring-demo-details"' in create_content
    assert 'name="demo_fill" value=""' in create_content
    assert "Civic Help Directory" in create_content
    assert "voidash/civic-help-directory" in create_content
    assert 'src="/static/src/authoring-demo-fill.js"' in create_content
    assert 'id="fill-demo-details"' not in edit_content
    assert 'id="authoring-demo-details"' not in edit_content


def test_demo_fill_script_only_mutates_existing_controls_without_submitting_or_fetching():
    """GOV-002/SEC-004: demo fill is client-side input assistance, never a write action."""
    script = (Path(settings.BASE_DIR) / "static/src/authoring-demo-fill.js").read_text()

    assert "form.submit" not in script
    assert "requestSubmit" not in script
    assert "fetch(" not in script
    assert 'namedItem("ministry")' in script
    assert "availableOptions.length === 1" in script
    assert "dispatchEvent" in script
    assert "option.selected = labels.includes" in script
    assert 'namedItem("demo_fill")' in script
    assert 'demoIntent.value = "civic-help-directory"' in script


@pytest.mark.integration
def test_marked_demo_fill_reuses_the_same_ministry_connected_project(client):
    """GOV-001/GOV-002/GIT-003: demo fill is idempotent for its canonical repository."""
    assignment = MinistryPublisherFactory()
    _verify_mfa(client, assignment.user)
    prepared = ProjectFactory(
        owner=assignment.user,
        ministry=assignment.ministry,
        title_en="Civic Help Directory",
        repository_url="https://github.com/voidash/civic-help-directory",
        default_branch="main",
    )
    connection = RepositoryConnectionFactory(
        project=prepared,
        full_name="voidash/civic-help-directory",
        is_public=True,
    )
    project_count = Project.objects.count()

    response = client.post(
        reverse("projects:authoring_create"),
        {
            "demo_fill": "civic-help-directory",
            "ministry": assignment.ministry.pk,
            "title_en": "Civic Help Directory",
            "title_ne": "नागरिक सहायता निर्देशिका",
            "summary_en": "A directory for public services.",
            "summary_ne": "सार्वजनिक सेवाहरूको निर्देशिका।",
            "repository_url": "https://github.com/voidash/civic-help-directory",
            "default_branch": "main",
            "data_classification": "public",
        },
    )

    assert response.status_code == 302
    assert response.url == reverse("projects:authoring_detail", kwargs={"slug": prepared.slug})
    assert Project.objects.count() == project_count
    connection.refresh_from_db()
    assert connection.project == prepared


@pytest.mark.integration
def test_unmarked_submission_keeps_normal_draft_creation_semantics(client):
    """GOV-001/GOV-002: repository reuse is exclusive to an explicit demo-fill intent."""
    assignment = MinistryPublisherFactory()
    _verify_mfa(client, assignment.user)
    prepared = ProjectFactory(
        owner=assignment.user,
        ministry=assignment.ministry,
        repository_url="https://github.com/voidash/civic-help-directory",
    )
    RepositoryConnectionFactory(
        project=prepared,
        full_name="voidash/civic-help-directory",
        is_public=True,
    )

    response = client.post(
        reverse("projects:authoring_create"),
        {
            "ministry": assignment.ministry.pk,
            "title_en": "A distinct ministry workstream",
            "title_ne": "फरक मन्त्रालय कार्यप्रवाह",
            "summary_en": "A separately governed workstream.",
            "summary_ne": "छुट्टै शासित कार्यप्रवाह।",
            "repository_url": "https://github.com/voidash/civic-help-directory",
            "data_classification": "public",
        },
    )

    assert response.status_code == 302
    assert Project.objects.filter(title_en="A distinct ministry workstream").exists()


@pytest.mark.integration
def test_demo_fill_cannot_reuse_another_ministrys_connected_project(client):
    """GOV-001/AUTH-006: a forged demo marker cannot cross a ministry boundary."""
    assignment = MinistryPublisherFactory()
    _verify_mfa(client, assignment.user)
    other_project = ProjectFactory(repository_url="https://github.com/voidash/civic-help-directory")
    RepositoryConnectionFactory(
        project=other_project,
        full_name="voidash/civic-help-directory",
        is_public=True,
    )

    response = client.post(
        reverse("projects:authoring_create"),
        {
            "demo_fill": "civic-help-directory",
            "ministry": assignment.ministry.pk,
            "title_en": "Civic Help Directory",
            "title_ne": "नागरिक सहायता निर्देशिका",
            "summary_en": "A directory for public services.",
            "summary_ne": "सार्वजनिक सेवाहरूको निर्देशिका।",
            "repository_url": "https://github.com/voidash/civic-help-directory",
            "data_classification": "public",
        },
    )

    assert response.status_code == 403
    assert not Project.objects.filter(
        owner=assignment.user, repository_url="https://github.com/voidash/civic-help-directory"
    ).exists()


def test_demo_fill_uses_the_rendered_mit_licence_label(client):
    """GOV-002: the demo helper selects the approved MIT licence shown by the form."""
    assignment = MinistryPublisherFactory()
    _verify_mfa(client, assignment.user)

    response = client.get(reverse("projects:authoring_create"))

    assert '"license":["MIT (MIT License)"]' in response.content.decode()


def test_ministry_selector_uses_nepali_names_and_placeholder(client):
    """NFR-I18N-01: the publisher form localizes its data choices, not only its labels."""
    assignment = MinistryPublisherFactory()
    assignment.ministry.name_ne = "सूचना प्रविधि विभाग"
    assignment.ministry.save(update_fields=["name_ne"])
    _verify_mfa(client, assignment.user)

    with translation.override("ne"):
        response = client.get(reverse("projects:authoring_create"))

    content = response.content.decode()
    assert response.status_code == 200
    assert "मन्त्रालय छान्नुहोस्" in content
    assert "सूचना प्रविधि विभाग" in content
    assert assignment.ministry.name_en not in content
