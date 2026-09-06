import posixpath
import re
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.staticfiles import finders


@pytest.mark.unit
def test_shared_shell_uses_the_verified_light_blueprint_system():
    """DSC-001/NFR-A11Y-01: public navigation has a consistent, trustworthy shell."""
    root = Path(settings.BASE_DIR)
    base = (root / "templates/base.html").read_text()
    tokens = (root / "static/src/tokens.css").read_text()
    shell = (root / "static/src/devnepal.css").read_text()

    assert "--color-bg: #f2f5f7;" in tokens
    assert "--color-surface: #e5e9ee;" in tokens
    assert "--color-text: #181c20;" in tokens
    assert "--color-accent: #5395fc;" in tokens
    assert 'font-family: "Inter"' in tokens
    assert '--font-body: "Inter"' in tokens
    assert '--font-heading: "Inter"' in tokens
    assert '"Noto Sans Devanagari"' in tokens
    # The shell used to forbid a second bar outright. It now carries one, and the
    # rules that kept the old ban worth having are asserted instead: the band lives
    # inside the header landmark, states the authority exactly once, links out so a
    # visitor can verify it, and stays a neutral surface rather than a second brand
    # colour competing with the accent.
    assert 'class="dn-gov-strip"' in base
    assert base.index('class="dn-product-header"') < base.index('class="dn-gov-strip"')
    assert base.count("नेपाल सरकार · Government of Nepal") == 1
    assert 'href="https://nepal.gov.np"' in base
    assert ".dn-gov-strip { background: var(--color-state);" in shell
    assert 'class="dn-product-header"' in base
    assert "background: var(--color-bg);" in shell
    assert "border-radius: 0;" in shell
    assert "--devnepal-header-bg" not in shell


@pytest.mark.unit
def test_shared_shell_has_one_ordered_design_cascade_and_a_real_text_face():
    """DSC-001/NFR-I18N-01: styling and bilingual typography load predictably."""
    root = Path(settings.BASE_DIR)
    base = (root / "templates/base.html").read_text()
    stylesheets = re.findall(
        r"rel=\"stylesheet\" href=\"\{% static '([^']+)' %\}(?:\?[^\"]+)?\"", base
    )

    assert stylesheets == [
        "vendor/primer/primer.css",
        "src/tokens.css",
        "src/base.css",
        "src/components.css",
        "src/devnepal.css",
        "src/onboarding.css",
        "src/public-discovery.css",
    ]
    shipped = sorted(path.name for path in (root / "static/fonts").glob("*.woff2"))

    assert shipped == ["inter-latin-variable.woff2"]
    for font in shipped:
        asset = root / "static/fonts" / font
        assert asset.is_file() and asset.stat().st_size > 0, font


def _clamp_ceiling(declaration: str, tokens: str = "") -> int:
    """The largest px a font-size declaration can render at.

    Page titles stay fluid, so they are read as the ceiling of their clamp. Every
    level below h1 is a flat scale step now, because a section heading that
    resizes with the viewport makes the ramp impossible to reason about against a
    card heading in another stylesheet; those are read through the token.
    """
    match = re.search(r"clamp\([^,]+,[^,]+,\s*(\d+)px\s*\)", declaration)
    if match:
        return int(match.group(1))
    match = re.search(r"font-size:\s*var\((--fs-[a-z\d]+)\)", declaration)
    assert match, declaration
    size = re.search(rf"{match.group(1)}: (\d+)px;", tokens)
    assert size, match.group(1)
    return int(size.group(1))


@pytest.mark.unit
def test_every_declared_font_face_resolves_to_a_served_asset():
    """DSC-001/NFR-I18N-01: the declared text face is deliverable, not a fallback.

    The shipped-asset check above proves a woff2 sits in static/fonts; it cannot
    prove tokens.css points at that file. A typo in the @font-face url leaves every
    page rendering in the system fallback with the whole suite green, so resolve
    each declared url through the staticfiles finders that actually serve it.
    """
    tokens = (Path(settings.BASE_DIR) / "static/src/tokens.css").read_text()
    declared = re.findall(r'@font-face\s*\{[^}]*src:\s*url\("([^"]+)"\)', tokens)

    assert declared, "tokens.css declares no @font-face source"
    for url in declared:
        served = finders.find(posixpath.normpath(posixpath.join("src", url)))
        assert served is not None, url
        assert Path(served).stat().st_size > 0, url


def _one(pattern, source):
    """Return a regex's first group, failing with the pattern rather than an AttributeError."""
    match = re.search(pattern, source)
    assert match, f"no match for {pattern}"
    return match.group(1)


@pytest.mark.unit
def test_display_scale_stays_ordered_below_the_hero_ceiling():
    """DSC-001: the heading ramp is one descending scale across three stylesheets.

    Inter sets far wider than the Barlow Condensed it replaced, so the ramp was
    stepped down. Its sizes now live in components.css (the hero), base.css (h1-h3,
    and the token h4 reads) and tokens.css, with nothing tying them together: a
    retune of one file can leave the hero smaller than a body h1, or restore the
    84px condensed ceiling that Inter cannot carry. Pin the ordering and the
    ceiling rather than the clamps, so deliberate retuning stays cheap.
    """
    root = Path(settings.BASE_DIR)
    base_css = (root / "static/src/base.css").read_text()
    components_css = (root / "static/src/components.css").read_text()
    tokens_css = (root / "static/src/tokens.css").read_text()

    hero = _clamp_ceiling(_one(r"\.hero h1 \{([^}]*)\}", components_css), tokens_css)
    headings = [
        _clamp_ceiling(_one(rf"\n{tag} \{{([^}}]*)\}}", base_css), tokens_css)
        for tag in ("h1", "h2", "h3")
    ]
    h4_token = _one(r"\nh4 \{[^}]*font-size: var\((--fs-[a-z\d]+)\)", base_css)
    ramp = [hero, *headings, int(_one(rf"{h4_token}:\s*(\d+)px", tokens_css))]

    assert ramp == sorted(set(ramp), reverse=True), ramp
    assert hero <= 72, hero


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
