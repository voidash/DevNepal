from pathlib import Path

import pytest
from django.conf import settings
from django.urls import reverse
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.ministries.tests.factories import MinistryPublisherFactory
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
    assert "ministry" not in script
    assert "dispatchEvent" in script
    assert "option.selected = labels.includes" in script
