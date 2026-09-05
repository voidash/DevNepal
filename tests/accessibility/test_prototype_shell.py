import re
from pathlib import Path

import pytest
from django.conf import settings


@pytest.mark.unit
def test_shared_shell_uses_the_verified_light_blueprint_system():
    """DSC-001/NFR-A11Y-01: public navigation has a consistent, trustworthy shell."""
    root = Path(settings.BASE_DIR)
    base = (root / "templates/base.html").read_text()
    tokens = (root / "static/src/tokens.css").read_text()
    shell = (root / "static/src/devnepal.css").read_text()

    assert "--color-bg: #f2f2f3;" in tokens
    assert "--color-surface: #e9e9ea;" in tokens
    assert "--color-text: #1d1f20;" in tokens
    assert "--color-accent: #3b6fd4;" in tokens
    assert 'font-family: "Barlow"' in tokens
    assert 'font-family: "Barlow Condensed"' in tokens
    assert '"Noto Sans Devanagari"' in tokens
    assert 'class="dn-gov-strip"' not in base
    assert 'class="dn-product-header"' in base
    assert "नेपाल सरकार · Government of Nepal" in base
    assert "background: var(--color-bg);" in shell
    assert "border-radius: 0;" in shell
    assert "--devnepal-header-bg" not in shell


@pytest.mark.unit
def test_shared_shell_has_one_ordered_design_cascade_and_real_barlow_assets():
    """DSC-001/NFR-I18N-01: styling and bilingual typography load predictably."""
    root = Path(settings.BASE_DIR)
    base = (root / "templates/base.html").read_text()
    stylesheets = re.findall(r"href=\"\{% static '([^']+)' %\}(?:\?[^\"]+)?\"", base)

    assert stylesheets == [
        "vendor/primer/primer.css",
        "src/tokens.css",
        "src/base.css",
        "src/components.css",
        "src/devnepal.css",
        "src/onboarding.css",
        "src/public-discovery.css",
    ]
    for font in (
        "barlow-latin-400.woff2",
        "barlow-latin-500.woff2",
        "barlow-latin-700.woff2",
        "barlow-condensed-latin-400.woff2",
        "barlow-condensed-latin-600.woff2",
    ):
        asset = root / "static/fonts" / font
        assert asset.is_file() and asset.stat().st_size > 0, font


@pytest.mark.django_db
@pytest.mark.unit
def test_rendered_shell_keeps_landmarks_and_mobile_navigation(client):
    """DSC-001/NFR-A11Y-01: every visitor can reach the responsive primary navigation."""
    from django.urls import reverse

    response = client.get(reverse("projects:home"))

    assert response.status_code == 200
    content = response.content.decode()
    assert 'class="btn dn-skip-link" href="#main-content"' in content
    assert '<header class="dn-product-header">' in content
    assert 'class="dn-primary-nav" aria-label="Primary"' in content
    assert 'class="mobile-nav"' in content
    assert 'id="main-content" tabindex="-1"' in content
