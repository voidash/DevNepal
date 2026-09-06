import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

import pytest
from django.conf import settings
from django.urls import reverse
from django.utils import translation

from apps.accounts.tests.factories import MemberProfileFactory, UserFactory
from apps.ministries.tests.factories import MinistryPublisherFactory, SuperAdminFactory
from apps.ministries.tests.factories import UserFactory as PublisherUserFactory
from apps.projects.enums import ProjectStatus
from apps.projects.tests.factories import ProjectFactory

pytestmark = pytest.mark.django_db

VOID_ELEMENTS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "source",
}


@dataclass
class Element:
    tag: str
    attributes: dict[str, str | None]
    parent: int | None


class DocumentParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements: list[Element] = []
        self.open_elements: list[int] = []

    def handle_starttag(self, tag, attrs):
        parent = self.open_elements[-1] if self.open_elements else None
        self.elements.append(Element(tag, dict(attrs), parent))
        if tag not in VOID_ELEMENTS:
            self.open_elements.append(len(self.elements) - 1)

    def handle_startendtag(self, tag, attrs):
        parent = self.open_elements[-1] if self.open_elements else None
        self.elements.append(Element(tag, dict(attrs), parent))

    def handle_endtag(self, tag):
        for index in range(len(self.open_elements) - 1, -1, -1):
            if self.elements[self.open_elements[index]].tag == tag:
                del self.open_elements[index:]
                return


def parse_document(content: bytes) -> DocumentParser:
    parser = DocumentParser()
    parser.feed(content.decode())
    return parser


def has_ancestor(parser: DocumentParser, element: Element, tag: str) -> bool:
    parent = element.parent
    while parent is not None:
        ancestor = parser.elements[parent]
        if ancestor.tag == tag:
            return True
        parent = ancestor.parent
    return False


def has_label(parser: DocumentParser, control: Element) -> bool:
    control_id = control.attributes.get("id")
    if control_id and any(
        element.tag == "label" and element.attributes.get("for") == control_id
        for element in parser.elements
    ):
        return True
    return has_ancestor(parser, control, "label") or bool(
        control.attributes.get("aria-label") or control.attributes.get("aria-labelledby")
    )


@pytest.fixture
def rendered_pages(client):
    project = ProjectFactory(status=ProjectStatus.OPEN_FOR_CONTRIBUTION)
    profile = MemberProfileFactory(
        user=UserFactory(username="accessibility-profile"),
        headline="Civic technologist",
    )

    pages = {
        "home": client.get(reverse("projects:home")),
        "catalog": client.get(reverse("projects:list")),
        "project detail": client.get(reverse("projects:detail", kwargs={"slug": project.slug})),
        "public profile": client.get(
            reverse("accounts:public_profile", kwargs={"username": profile.user.username})
        ),
    }

    client.force_login(UserFactory(username="accessibility-dashboard"))
    pages["dashboard"] = client.get(reverse("accounts:dashboard"))

    publisher = PublisherUserFactory(username="accessibility-publisher")
    MinistryPublisherFactory(
        user=publisher,
        assigned_by=SuperAdminFactory(username="accessibility-admin"),
    )
    client.force_login(publisher)
    pages["MFA setup"] = client.get(reverse("accounts:mfa_setup"))

    assert all(response.status_code == 200 for response in pages.values())
    return pages


@pytest.mark.unit
def test_rendered_pages_provide_named_landmarks_and_a_skip_target(rendered_pages):
    """A8/NFR-A11Y-01: keyboard and screen-reader users can bypass shared navigation."""
    for page_name, response in rendered_pages.items():
        document = parse_document(response.content)
        tags = [element.tag for element in document.elements]
        main = [element for element in document.elements if element.tag == "main"]
        banner = [
            element
            for element in document.elements
            if element.tag == "header"
            and element.parent is not None
            and document.elements[element.parent].tag == "body"
        ]

        assert len(banner) == 1, page_name
        assert "dn-product-header" in (banner[0].attributes.get("class") or ""), page_name
        assert len(main) == 1, page_name
        assert main[0].attributes.get("id") == "main-content", page_name
        assert main[0].attributes.get("tabindex") == "-1", page_name
        assert tags.count("footer") == 1, page_name
        assert all(
            element.attributes.get("aria-label")
            for element in document.elements
            if element.tag == "nav"
        ), page_name
        assert any(
            element.tag == "a"
            and "dn-skip-link" in (element.attributes.get("class") or "").split()
            and element.attributes.get("href") == "#main-content"
            for element in document.elements
        ), page_name


@pytest.mark.unit
def test_rendered_pages_carry_government_identity_inside_the_light_header(rendered_pages):
    """A8/NFR-A11Y-01/GOV-011: every page names the public authority in its header."""
    for page_name, response in rendered_pages.items():
        document = parse_document(response.content)
        body_children = [
            element
            for element in document.elements
            if element.parent is not None and document.elements[element.parent].tag == "body"
        ]

        shell_order = [element.tag for element in body_children]
        assert shell_order[:2] == ["a", "header"], page_name
        assert "Government of Nepal" in response.content.decode(), page_name
        assert "नेपाल सरकार" in response.content.decode(), page_name


@pytest.mark.unit
def test_rendered_pages_expose_the_language_switch_without_inline_handlers(
    rendered_pages,
):
    """A8/NFR-A11Y-01: locale controls work without pointer-only handlers."""
    for page_name, response in rendered_pages.items():
        document = parse_document(response.content)
        language_forms = [
            element
            for element in document.elements
            if element.tag == "form"
            and "lang-switch" in (element.attributes.get("class") or "").split()
        ]
        language_buttons = [
            element
            for element in document.elements
            if element.tag == "button" and has_ancestor(document, element, "form")
        ]

        assert "onclick=" not in response.content.decode().lower(), page_name
        assert len(language_forms) == 1, page_name
        assert language_forms[0].attributes.get("method") == "post", page_name
        assert language_forms[0].attributes.get("aria-label"), page_name
        assert {
            button.attributes.get("value")
            for button in language_buttons
            if button.attributes.get("name") == "language"
        } == {"en", "ne"}, page_name


@pytest.mark.unit
def test_nepali_documents_declare_the_active_document_language(client):
    """A8/NFR-A11Y-01: assistive technology receives the active document language.

    The document language is English or Nepali.
    """
    with translation.override("ne"):
        response = client.get(reverse("projects:home"))

    document = parse_document(response.content)
    html = next(element for element in document.elements if element.tag == "html")

    assert html.attributes.get("lang") == "ne"


@pytest.mark.unit
def test_rendered_forms_and_images_have_programmatic_text_alternatives(rendered_pages):
    """A8/NFR-A11Y-01: form controls and informative images expose accessible names."""
    for page_name, response in rendered_pages.items():
        document = parse_document(response.content)
        controls = [
            element
            for element in document.elements
            if element.tag in {"input", "select", "textarea"}
            and element.attributes.get("type") != "hidden"
        ]
        images = [element for element in document.elements if element.tag == "img"]

        assert all(has_label(document, control) for control in controls), page_name
        assert all("alt" in image.attributes for image in images), page_name
        assert all(
            image.attributes.get("alt") == ""
            for image in images
            if "decorative" in (image.attributes.get("class") or "").split()
            or image.attributes.get("aria-hidden") == "true"
        ), page_name


@pytest.mark.unit
def test_catalog_cards_and_accountability_sheets_keep_textual_state(rendered_pages):
    """A2.1/A2.2/NFR-A11Y-01/GOV-011: cards and sheets state their meaning.

    Status is never carried by shape or color alone: every catalog card renders the
    localized status text, provenance is a labeled "Official"/"Community" Label, and
    the project detail page renders contribution and accountability facts as text.
    """
    catalog = rendered_pages["catalog"]
    detail = rendered_pages["project detail"]
    catalog_document = parse_document(catalog.content)
    detail_document = parse_document(detail.content)

    cards = [
        element
        for element in catalog_document.elements
        if element.tag == "article"
        and {"card", "blueprint"}.issubset(set((element.attributes.get("class") or "").split()))
    ]
    assert cards, "catalog"
    assert catalog.context["projects"].paginator.count >= len(cards)

    provenance = [
        element
        for element in catalog_document.elements
        if element.tag == "span" and "Label" in (element.attributes.get("class") or "").split()
    ]
    assert provenance, "catalog"

    accountability = [
        element
        for element in detail_document.elements
        if (element.attributes.get("class") or "") == "dn-accountability"
    ]
    assert len(accountability) >= 2, "project detail"
    cells = [
        element
        for element in detail_document.elements
        if has_ancestor(detail_document, element, "div")
        and element.attributes.get("class") == "dn-accountability-item"
    ]
    assert len(cells) >= 6, "project detail"

    content = detail.content.decode()
    assert "Maintainers" in content, "project detail"
    assert "Response commitment" in content, "project detail"
    assert "Suitability checklist not started" not in content, "project detail"


@pytest.mark.unit
def test_accessibility_css_contracts_cover_focus_motion_and_target_rules():
    """A8/NFR-A11Y-01: design-system CSS preserves focus, motion, and target rules."""
    static_dir = Path(settings.BASE_DIR) / "static/src"
    devnepal_css = (static_dir / "devnepal.css").read_text()
    base_css = (static_dir / "base.css").read_text()
    tokens_css = (static_dir / "tokens.css").read_text()

    assert "body { min-width: 320px" in devnepal_css
    assert "html { scroll-behavior: smooth" not in devnepal_css
    assert "min-height: 44px" in devnepal_css
    assert "--devnepal-header-bg" not in devnepal_css
    for banned in ("linear-gradient(", "radial-gradient(", "backdrop-filter:"):
        assert banned not in devnepal_css
    assert ":focus-visible" in base_css
    assert "outline:" in base_css
    assert ".dn-product-header :focus-visible" in base_css
    assert "@media (prefers-reduced-motion: reduce)" in base_css
    assert "scroll-behavior: auto !important;" in base_css
    assert "transition-duration: 0.01ms !important;" in base_css
    assert "--target-min: 44px;" in tokens_css
    assert re.search(r"\.dn-tab\s*\{[^}]*min-height: 44px", devnepal_css, re.DOTALL)
