import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.urls import reverse

from apps.accounts.enums import LinkType
from apps.accounts.models import MemberLink
from apps.accounts.tests.factories import MemberLinkFactory, UserFactory

pytestmark = pytest.mark.django_db


@pytest.mark.unit
@pytest.mark.parametrize("link_type", [choice.value for choice in LinkType])
def test_mem006_u1_link_types_allowlisted(link_type):
    """MEM-006-U1: link types are restricted to the allowlist (GitHub, Medium, website...)."""
    user = UserFactory()
    link = MemberLink(user=user, link_type=link_type, url="https://example.com/")
    link.full_clean()


@pytest.mark.unit
def test_mem006_u1_link_type_outside_allowlist_rejected():
    """MEM-006-U1: a link type outside the allowlist fails validation."""
    user = UserFactory()
    link = MemberLink(user=user, link_type="mastodon", url="https://example.com/")
    with pytest.raises(ValidationError) as excinfo:
        link.full_clean()
    assert "link_type" in excinfo.value.error_dict


@pytest.mark.unit
@pytest.mark.parametrize(
    "unsafe_url",
    [
        "javascript:alert(1)",
        "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
        "ftp://files.example.com/payload",
    ],
)
def test_mem007_u1_unsafe_url_schemes_rejected(unsafe_url):
    """MEM-007-U1, SEC-004: javascript:, data:, and other unsafe schemes are rejected on clean."""
    user = UserFactory()
    link = MemberLink(user=user, link_type=LinkType.PORTFOLIO, url=unsafe_url)
    with pytest.raises(ValidationError) as excinfo:
        link.full_clean()
    assert "url" in excinfo.value.error_dict


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw_url", "normalized_url"),
    [
        ("HTTPS://GitHub.COM/kxitm", "https://github.com/kxitm"),
        ("https://github.com", "https://github.com/"),
        ("https://परीक्षा.example.com", "https://xn--11b5bs3a9aj6g.example.com/"),
        ("https://github.com/kxitm?tab=repos", "https://github.com/kxitm?tab=repos"),
    ],
)
def test_mem007_u2_urls_normalized_before_save(raw_url, normalized_url):
    """MEM-007-U2: URLs are normalized (host case, trailing slash, IDN) before save."""
    user = UserFactory()
    link = MemberLink(user=user, link_type=LinkType.GITHUB, url=raw_url)
    link.save()
    stored = MemberLink.objects.get(pk=link.pk)
    assert stored.url == normalized_url


@pytest.mark.unit
def test_mem007_u2_normalized_urls_deduplicated_per_user():
    """MEM-007-U2: normalization makes casing variants of the same URL collide on uniqueness."""
    user = UserFactory()
    MemberLinkFactory(user=user, url="https://github.com/sita")
    with pytest.raises(IntegrityError):
        MemberLinkFactory(user=user, url="HTTPS://GitHub.COM/sita")


def link_formset_data(*rows):
    data = {
        "links-TOTAL_FORMS": str(len(rows)),
        "links-INITIAL_FORMS": "0",
        "links-MIN_NUM_FORMS": "0",
        "links-MAX_NUM_FORMS": "8",
    }
    for index, row in enumerate(rows):
        for name, value in row.items():
            data[f"links-{index}-{name}"] = value
        if "id" in row:
            data["links-INITIAL_FORMS"] = str(int(data["links-INITIAL_FORMS"]) + 1)
    return data


def existing_row(link):
    return {
        "id": str(link.pk),
        "link_type": link.link_type,
        "url": link.url,
        "label": link.label,
    }


@pytest.mark.integration
@pytest.mark.django_db
def test_mem006_i1_profile_editor_saves_allowlisted_links_with_publicity_flag(client):
    """MEM-006-I1: the profile editor adds allowlisted MemberLink rows with is_public."""
    user = UserFactory()
    client.force_login(user)
    data = link_formset_data(
        {
            "link_type": "github",
            "url": "https://github.com/sita",
            "label": "Sita on GitHub",
            "is_public": "on",
        },
        {"link_type": "portfolio", "url": "https://sita.example/work", "label": ""},
    )

    response = client.post(reverse("accounts:profile_edit"), data)

    assert response.status_code == 302
    github = MemberLink.objects.get(user=user, link_type=LinkType.GITHUB)
    assert github.url == "https://github.com/sita"
    assert github.label == "Sita on GitHub"
    assert github.is_public is True
    portfolio = MemberLink.objects.get(user=user, link_type=LinkType.PORTFOLIO)
    assert portfolio.is_public is False


@pytest.mark.integration
@pytest.mark.django_db
def test_mem007_i1_profile_editor_rejects_unsafe_scheme_without_saving(client):
    """MEM-007-U1/SEC-004: javascript: URLs are refused by the editor and never stored."""
    user = UserFactory()
    client.force_login(user)

    response = client.post(
        reverse("accounts:profile_edit"),
        link_formset_data({"link_type": "website", "url": "javascript:alert(1)", "label": ""}),
    )

    assert response.status_code == 400
    assert "url" in response.context["link_formset"].errors[0]
    assert not MemberLink.objects.filter(user=user).exists()


@pytest.mark.integration
@pytest.mark.django_db
def test_mem007_u2_profile_editor_rejects_normalized_duplicate_urls(client):
    """MEM-007-U2: casing variants of the same URL cannot be saved twice by one member."""
    user = UserFactory()
    link = MemberLinkFactory(user=user, url="https://github.com/sita", link_type=LinkType.GITHUB)
    client.force_login(user)

    response = client.post(
        reverse("accounts:profile_edit"),
        link_formset_data(
            existing_row(link),
            {"link_type": "website", "url": "HTTPS://GitHub.COM/sita", "label": "duplicate"},
        ),
    )

    assert response.status_code == 400
    assert "url" in response.context["link_formset"].errors[1]
    assert MemberLink.objects.filter(user=user).count() == 1


@pytest.mark.integration
@pytest.mark.django_db
def test_mem006_i1_profile_editor_removes_existing_link(client):
    """MEM-006-I1: an existing link row is removed through the editor on save."""
    user = UserFactory()
    link = MemberLinkFactory(user=user, url="https://github.com/old", link_type=LinkType.GITHUB)
    client.force_login(user)
    row = existing_row(link)
    row["DELETE"] = "on"

    response = client.post(
        reverse("accounts:profile_edit"),
        link_formset_data(row),
    )

    assert response.status_code == 302
    assert not MemberLink.objects.filter(pk=link.pk).exists()
