import re

import pytest
from django.urls import reverse

from apps.accounts.models import MemberProfile
from apps.ministries.tests.factories import MinistryPublisherFactory
from apps.projects.tests.factories import SuperAdminFactory, UserFactory

pytestmark = [pytest.mark.django_db, pytest.mark.acceptance]


def make_member(username):
    user = UserFactory(username=username)
    user.set_password("hub-password-2026")
    user.save(update_fields=["password"])
    MemberProfile.objects.create(user=user)
    return user


def verify_mfa(client, user):
    from django_otp.oath import totp
    from django_otp.plugins.otp_totp.models import TOTPDevice

    client.force_login(user)
    setup_url = reverse("accounts:mfa_setup")
    client.get(setup_url)
    device = TOTPDevice.objects.get(user=user)
    device.last_t = -1
    device.save(update_fields=["last_t"])
    token = totp(
        device.bin_key, step=device.step, t0=device.t0, digits=device.digits, drift=device.drift
    )
    assert client.post(setup_url, {"token": token}).status_code == 302


def homepage_links(client):
    html = client.get(reverse("projects:home")).content.decode()
    hrefs = set(re.findall(r'href="([^"]+)"', html))
    internal = {
        h
        for h in hrefs
        if h.startswith("/")
        and not h.startswith("//")
        and "setlang" not in h
        and not h.startswith("/static/")
    }
    internal.discard("/webhooks/github/")
    return sorted(internal)


def assert_links_resolve(client, links):
    broken = []
    for href in links:
        response = client.get(href)
        if response.status_code not in (200, 301, 302):
            broken.append(f"{href} -> {response.status_code}")
    assert not broken, f"homepage links are broken: {broken}"


@pytest.mark.unit
def test_every_homepage_link_resolves_for_anonymous_visitors(client):
    """NFR-A11Y-01/DSC-001: the homepage hub never offers a link that does not resolve."""
    links = homepage_links(client)

    assert links, "homepage exposed no links at all"
    assert_links_resolve(client, links)
    assert any("login" in link for link in links)


@pytest.mark.unit
def test_every_homepage_link_resolves_without_legacy_member_shortcuts(client):
    """NTF-001/MEM-002: legacy members do not expand the minimal public shell."""
    user = make_member("hub-member")
    client.force_login(user)

    links = homepage_links(client)

    assert not any("dashboard" in link for link in links)
    assert not any("applications" in link for link in links)
    assert not any("notifications" in link for link in links)
    assert_links_resolve(client, links)


@pytest.mark.unit
def test_every_homepage_link_resolves_for_mfa_verified_super_admins(client):
    """SEC-005/DSC-001: a privileged account still receives only visitor-shell links."""
    admin = SuperAdminFactory(username="hub-admin")
    MinistryPublisherFactory(user=UserFactory(username="hub-publisher-seed"))
    verify_mfa(client, admin)

    links = homepage_links(client)

    assert not any("ministries" in link for link in links)
    assert not any("cases" in link for link in links)
    assert not any("audit" in link for link in links)
    assert_links_resolve(client, links)
