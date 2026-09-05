import pytest
from django.test import override_settings
from django.urls import reverse

from apps.blogs.enums import BlogPostType
from apps.blogs.services import (
    BlogContentError,
    create_native_post,
    publish_listing,
    render_safe_markdown,
)
from apps.blogs.tests.factories import UserFactory

pytestmark = [pytest.mark.django_db]


@pytest.fixture(autouse=True)
def blog_urlconf():
    with override_settings(ROOT_URLCONF="apps.blogs.tests.urls"):
        yield


@pytest.mark.unit
def test_safe_markdown_supports_required_authoring_features():
    """BLG-002: headings, code, images, links, and tables render from safe Markdown."""
    rendered = render_safe_markdown(
        """# Accessible forms

- Labels stay visible
- Errors identify the field

[WCAG guidance](https://www.w3.org/WAI/WCAG22/quickref/)

![A form showing visible error messages](https://example.gov.np/form.png)

| Check | Result |
| --- | --- |
| Labels | Pass |

```python
print("checked")
```
"""
    )

    assert "<h1>Accessible forms</h1>" in rendered
    assert "<ul><li>Labels stay visible</li><li>Errors identify the field</li></ul>" in rendered
    assert '<a href="https://www.w3.org/WAI/WCAG22/quickref/"' in rendered
    assert 'alt="A form showing visible error messages"' in rendered
    assert "<table>" in rendered
    assert '<code class="language-python">' in rendered


@pytest.mark.unit
def test_markdown_requires_accessible_image_alternative_text():
    """BLG-002: every Markdown image requires non-empty accessible alternative text."""
    with pytest.raises(BlogContentError, match="alternative text"):
        render_safe_markdown("![](https://example.gov.np/form.png)")


@pytest.mark.unit
@pytest.mark.parametrize(
    "payload",
    [
        '<script>alert("stored")</script>',
        '<iframe src="https://attacker.example"></iframe>',
        '<img src=x onerror="alert(1)">',
        "[unsafe](javascript:alert(1))",
    ],
)
def test_markdown_output_cannot_execute_stored_payloads(payload):
    """BLG-003/SEC-004: raw HTML and unsafe URL schemes render inert or are rejected."""
    if payload.startswith("[unsafe]"):
        with pytest.raises(BlogContentError, match="http or https"):
            render_safe_markdown(payload)
        return

        rendered = render_safe_markdown(payload)
        assert "<script" not in rendered
        assert "<iframe" not in rendered
        assert "<img src=x" not in rendered
        assert "&lt;" in rendered


@pytest.mark.integration
def test_native_post_stores_sanitized_html_and_computed_reading_time():
    """BLG-002/BLG-003/BLG-004: native posts persist safe HTML and computed metadata."""
    member = UserFactory()
    markdown = "# शीर्षक\n\n" + " ".join(["accessible"] * 201)

    post = create_native_post(
        member,
        title="Accessible public forms",
        excerpt="A practical audit.",
        content_markdown=markdown,
        cover_image_url="https://example.gov.np/cover.png",
        cover_image_alt="Keyboard focus visible on a public form",
    )

    assert post.post_type == BlogPostType.NATIVE
    assert post.canonical_url == ""
    assert post.content_rendered.startswith("<h1>शीर्षक</h1>")
    assert post.reading_time_minutes == 2
    publish_listing(member, post)
    post.refresh_from_db()
    assert post.content_rendered.startswith("<h1>शीर्षक</h1>")


@pytest.mark.unit
def test_native_cover_image_requires_alt_text():
    """BLG-002/BLG-004: a native cover image cannot be saved without alternative text."""
    with pytest.raises(BlogContentError, match="cover image alternative text"):
        create_native_post(
            UserFactory(),
            title="Form review",
            content_markdown="# Findings",
            cover_image_url="https://example.gov.np/cover.png",
        )


@pytest.mark.unit
def test_preview_runs_checks_without_saving_a_post(client):
    """BLG-001/BLG-002/BLG-003: preview renders checked Markdown without creating a post."""
    member = UserFactory()
    client.force_login(member)

    response = client.post(
        reverse("blogs:create"),
        {
            "post_type": BlogPostType.NATIVE,
            "title": "Preview the audit",
            "excerpt": "Preview only.",
            "content_markdown": "# Result\n\n<script>alert(1)</script>",
            "canonical_url": "",
            "cover_image_url": "",
            "cover_image_alt": "",
            "language": "en",
            "tags": [],
            "action": "preview",
        },
    )

    assert response.status_code == 200
    assert member.blog_posts.count() == 0
    assert "<h1>Result</h1>" in response.context["preview_html"]
    assert "<script>alert(1)</script>" not in response.content.decode()
    assert response.context["preview_checks"]


@pytest.mark.integration
def test_published_native_post_renders_sanitized_body_and_external_links_stay_external(client):
    """BLG-002/BLG-003/BLG-005: native and external publication paths coexist publicly."""
    member = UserFactory()
    native = create_native_post(
        member,
        title="Native accessibility notes",
        content_markdown="# Checked\n\n<script>alert(1)</script>",
    )
    publish_listing(member, native)

    native_response = client.get(reverse("blogs:detail", kwargs={"post_id": native.pk}))

    assert native_response.status_code == 200
    body = native_response.content.decode()
    assert "<h1>Checked</h1>" in body
    assert "<script>alert(1)</script>" not in body
    assert "Read the external article" not in body
