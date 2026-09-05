import html
import re
from urllib.parse import urlsplit

from apps.taxonomy.fields import normalize_nfc

INLINE_TOKEN = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)|\[([^\]]+)\]\(([^)\s]+)\)|`([^`]+)`")
TABLE_DIVIDER = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
LANGUAGE_NAME = re.compile(r"^[A-Za-z0-9_+-]+$")


class MarkdownValidationError(ValueError):
    """Safe Markdown could not be rendered because author input violates the policy."""


def _safe_url(value):
    normalized = normalize_nfc(value.strip())
    parsed = urlsplit(normalized)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise MarkdownValidationError("Markdown links and images must use http or https URLs")
    return normalized


def _render_inline(value):
    rendered = []
    cursor = 0
    for match in INLINE_TOKEN.finditer(value):
        rendered.append(html.escape(value[cursor : match.start()]))
        image_alt, image_url, link_text, link_url, code = match.groups()
        if image_url is not None:
            alt = normalize_nfc(image_alt.strip())
            if not alt:
                raise MarkdownValidationError("Markdown images require accessible alternative text")
            rendered.append(
                f'<img src="{html.escape(_safe_url(image_url), quote=True)}" '
                f'alt="{html.escape(alt, quote=True)}">'
            )
        elif link_url is not None:
            rendered.append(
                f'<a href="{html.escape(_safe_url(link_url), quote=True)}" '
                f'rel="noopener noreferrer">{html.escape(link_text)}</a>'
            )
        else:
            rendered.append(f"<code>{html.escape(code)}</code>")
        cursor = match.end()
    rendered.append(html.escape(value[cursor:]))
    return "".join(rendered)


def _table_cells(line):
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def render_markdown(value):
    """Render the BLG-002 subset while treating all raw HTML as text."""
    source = normalize_nfc(value or "")
    lines = source.splitlines()
    rendered = []
    paragraph = []
    index = 0

    def flush_paragraph():
        if paragraph:
            rendered.append(f"<p>{_render_inline(' '.join(paragraph))}</p>")
            paragraph.clear()

    while index < len(lines):
        line = lines[index]
        if line.startswith("```"):
            flush_paragraph()
            language = line[3:].strip()
            if language and not LANGUAGE_NAME.fullmatch(language):
                raise MarkdownValidationError("code block language contains unsupported characters")
            index += 1
            code_lines = []
            while index < len(lines) and not lines[index].startswith("```"):
                code_lines.append(lines[index])
                index += 1
            if index == len(lines):
                raise MarkdownValidationError("code block is missing its closing fence")
            escaped_language = html.escape(language, quote=True)
            class_name = f' class="language-{escaped_language}"' if language else ""
            escaped_code = html.escape(chr(10).join(code_lines))
            rendered.append(f"<pre><code{class_name}>{escaped_code}</code></pre>")
        elif index + 1 < len(lines) and TABLE_DIVIDER.fullmatch(lines[index + 1]):
            flush_paragraph()
            headers = _table_cells(line)
            index += 2
            rows = []
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                rows.append(_table_cells(lines[index]))
                index += 1
            head = "".join(f'<th scope="col">{_render_inline(cell)}</th>' for cell in headers)
            body = "".join(
                "<tr>" + "".join(f"<td>{_render_inline(cell)}</td>" for cell in row) + "</tr>"
                for row in rows
            )
            rendered.append(f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>")
            continue
        elif match := re.match(r"^(#{1,6})\s+(.+)$", line):
            flush_paragraph()
            level = len(match.group(1))
            rendered.append(f"<h{level}>{_render_inline(match.group(2).strip())}</h{level}>")
        elif not line.strip():
            flush_paragraph()
        else:
            paragraph.append(line.strip())
        index += 1

    flush_paragraph()
    return "\n".join(rendered)
