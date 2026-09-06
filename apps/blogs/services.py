import logging
import math
import re
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from http.client import HTTPSConnection
from ipaddress import ip_address
from urllib.parse import urljoin, urlsplit

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounts.services import normalize_public_url, require_privileged_mfa
from apps.audit.services import record_audit
from apps.blogs.enums import BlogModerationState, BlogPostType, BlogStatus
from apps.blogs.markdown import MarkdownValidationError, render_markdown
from apps.blogs.models import BlogPost, BlogVersion
from apps.ministries.enums import PublisherStatus
from apps.ministries.models import MinistryPublisher
from apps.ministries.services import is_publisher_active
from apps.projects.enums import ProjectStatus, ProjectType
from apps.projects.models import Project
from apps.taxonomy.enums import ContentLanguage, TermVocabulary
from apps.taxonomy.fields import normalize_nfc

logger = logging.getLogger(__name__)

LISTING_FIELDS = frozenset(
    {
        "title",
        "excerpt",
        "canonical_url",
        "cover_image_url",
        "cover_image_alt",
        "tags",
        "language",
        "reading_time_minutes",
    }
)
NATIVE_FIELDS = frozenset(
    {
        "title",
        "excerpt",
        "content_markdown",
        "canonical_url",
        "cover_image_url",
        "cover_image_alt",
        "tags",
        "language",
    }
)
HTTP_URL_VALIDATOR = URLValidator(schemes=["http", "https"])
OFFICIAL_SEAL_PHRASES = tuple(
    normalize_nfc(phrase)
    for phrase in ("Government of Nepal", "श्रीमान्", "official seal", "नेपाल सरकार")
)

MODERATION_TRANSITIONS = {
    BlogModerationState.NOT_REVIEWED: frozenset({BlogModerationState.UNDER_REVIEW}),
    BlogModerationState.UNDER_REVIEW: frozenset(
        {BlogModerationState.RESTRICTED, BlogModerationState.REINSTATED}
    ),
    BlogModerationState.RESTRICTED: frozenset({BlogModerationState.REINSTATED}),
    BlogModerationState.REINSTATED: frozenset({BlogModerationState.UNDER_REVIEW}),
}


class BlogServiceError(Exception):
    """Base class for blogs service failures."""


class BlogListingFieldError(BlogServiceError):
    """Listing payload carries a field outside the D13 link-listing subset or an invalid value."""


class BlogCanonicalUrlError(BlogServiceError):
    """A listing canonical URL is missing or outside the http/https allowlist."""


class BlogExternalArticleUrlError(BlogServiceError):
    """An external article address is not a safe, public HTTPS URL."""


class BlogProvenanceError(BlogServiceError):
    """An external article was submitted without an authorship or listing-rights confirmation."""


class BlogExternalMetadataError(BlogServiceError):
    """Source metadata cannot be safely retrieved from an external article address."""


@dataclass(frozen=True)
class ExternalArticleMetadata:
    canonical_url: str
    source_name: str
    title: str
    excerpt: str
    language: str


class _ExternalMetadataParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.description = ""
        self.language = ""
        self.open_graph_title = ""
        self.title_parts = []
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "html" and attributes.get("lang"):
            self.language = attributes["lang"]
        if tag == "title":
            self._in_title = True
        if tag != "meta":
            return
        name = attributes.get("name", "").lower()
        property_name = attributes.get("property", "").lower()
        content = attributes.get("content", "")
        if content and property_name == "og:title" and not self.open_graph_title:
            self.open_graph_title = content
        if content and name == "description" and not self.description:
            self.description = content
        if content and property_name == "og:description" and not self.description:
            self.description = content

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title_parts.append(data)


class _PinnedHTTPSConnection(HTTPSConnection):
    def __init__(self, host, port, connect_address):
        super().__init__(host=host, port=port, timeout=5)
        self._connect_address = connect_address

    def connect(self):
        sock = socket.create_connection((self._connect_address, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise


class BlogOwnershipError(BlogServiceError):
    """Only the active author of a listing may perform this action."""


class BlogStateError(BlogServiceError):
    """Requested lifecycle transition is invalid for the listing's current status."""


class BlogModerationTransitionError(BlogServiceError):
    """Requested moderation transition is invalid for the post's current state."""


class OfficialPostPermissionError(BlogServiceError):
    """BLG-007: publishing an official post requires an active publisher role and verified MFA."""


class OfficialPostProjectError(BlogServiceError):
    """BLG-007: an official post must identify a public project owned by the publisher ministry."""


class OfficialSealWordingError(BlogServiceError):
    """BR-009: personal listings must not carry official-seal wording."""


class BlogContentError(BlogServiceError):
    """Native article content violates the safe Markdown or accessibility contract."""


def _require_active_author(actor, post):
    if (
        actor is None
        or not getattr(actor, "is_active", False)
        or not getattr(actor, "is_authenticated", False)
        or actor != post.author
    ):
        raise BlogOwnershipError("only the active author may perform this action")


def _clean_canonical_url(value):
    if not value or not str(value).strip():
        raise BlogCanonicalUrlError("a canonical URL is required for a link listing")
    url = normalize_public_url(value)
    try:
        HTTP_URL_VALIDATOR(url)
    except ValidationError as exc:
        raise BlogCanonicalUrlError("canonical URL must use the http or https scheme") from exc
    return url


def clean_external_article_url(value):
    """BLG-005/MEM-007: accept a normalized, public HTTPS article address without credentials."""
    raw_value = normalize_nfc(value.strip()) if isinstance(value, str) else value
    raw_parts = urlsplit(raw_value)
    if raw_parts.username is not None or raw_parts.password is not None:
        raise BlogExternalArticleUrlError(_("Article address must not include credentials."))
    try:
        url = _clean_canonical_url(value)
    except BlogCanonicalUrlError as exc:
        raise BlogExternalArticleUrlError(_("Article address must be a valid HTTPS URL.")) from exc
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise BlogExternalArticleUrlError(_("Article address must use HTTPS."))
    host = parts.hostname
    if not host:
        raise BlogExternalArticleUrlError(_("Article address must have a public hostname."))
    try:
        ip_address(host)
    except ValueError:
        pass
    else:
        raise BlogExternalArticleUrlError(_("Article address must have a public hostname."))
    host = host.lower().rstrip(".")
    if host in {"localhost", "local"} or host.endswith((".localhost", ".local")):
        raise BlogExternalArticleUrlError(_("Article address must have a public hostname."))
    return url


def _external_source_name(url):
    host = urlsplit(url).hostname or ""
    names = {
        "medium.com": "Medium",
        "dev.to": "Dev.to",
        "hashnode.com": "Hashnode",
        "substack.com": "Substack",
    }
    normalized_host = host.removeprefix("www.")
    for domain, name in names.items():
        if normalized_host == domain or normalized_host.endswith(f".{domain}"):
            return name
    return normalized_host


def _public_address_for(host, port):
    try:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise BlogExternalMetadataError("source hostname could not be resolved") from exc
    for record in records:
        address = record[4]
        candidate = ip_address(address[0])
        if candidate.is_global:
            return str(candidate)
    raise BlogExternalMetadataError("source hostname does not resolve to a public address")


def _compact_external_metadata(value, limit):
    return normalize_nfc(" ".join(value.split())).strip()[:limit]


def fetch_external_article_metadata(value):
    """BLG-005/MEM-007: retrieve bounded metadata over pinned, public HTTPS connections only."""
    url = clean_external_article_url(value)
    for _redirect_attempt in range(4):
        parts = urlsplit(url)
        try:
            port = parts.port or 443
        except ValueError as exc:
            raise BlogExternalMetadataError("source address has an invalid port") from exc
        address = _public_address_for(parts.hostname, port)
        connection = _PinnedHTTPSConnection(parts.hostname, port, address)
        target = parts.path or "/"
        if parts.query:
            target = f"{target}?{parts.query}"
        try:
            connection.request(
                "GET",
                target,
                headers={
                    "Accept": "text/html,application/xhtml+xml",
                    "User-Agent": "DevNepal external article metadata",
                },
            )
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location:
                    raise BlogExternalMetadataError("source redirected without a destination")
                url = clean_external_article_url(urljoin(url, location))
                continue
            if response.status < 200 or response.status >= 300:
                raise BlogExternalMetadataError("source did not return a readable article page")
            content_type = response.getheader("Content-Type", "").lower()
            if not content_type.startswith(("text/html", "application/xhtml+xml")):
                raise BlogExternalMetadataError("source did not return an HTML article page")
            content_length = response.getheader("Content-Length")
            if content_length and int(content_length) > 262144:
                raise BlogExternalMetadataError("source metadata page is too large")
            body = response.read(262145)
        except (OSError, ValueError) as exc:
            raise BlogExternalMetadataError("source metadata could not be retrieved") from exc
        finally:
            connection.close()
        if len(body) > 262144:
            raise BlogExternalMetadataError("source metadata page is too large")
        charset = response.headers.get_content_charset("utf-8")
        try:
            decoded_body = body.decode(charset, errors="replace")
        except LookupError:
            decoded_body = body.decode("utf-8", errors="replace")
        parser = _ExternalMetadataParser()
        parser.feed(decoded_body)
        parser.close()
        title = _compact_external_metadata(
            parser.open_graph_title or " ".join(parser.title_parts), 200
        )
        if not title:
            raise BlogExternalMetadataError("source page does not provide an article title")
        language = (
            ContentLanguage.NEPALI
            if parser.language.lower().startswith("ne")
            else ContentLanguage.ENGLISH
        )
        return ExternalArticleMetadata(
            canonical_url=url,
            source_name=_external_source_name(url),
            title=title,
            excerpt=_compact_external_metadata(parser.description, 5000),
            language=language,
        )
    raise BlogExternalMetadataError("source redirected too many times")


def _clean_optional_url(value, field_name):
    if not value or not str(value).strip():
        return ""
    try:
        return _clean_canonical_url(value)
    except BlogCanonicalUrlError as exc:
        raise BlogContentError(f"{field_name} must use the http or https scheme") from exc


def _clean_listing_fields(fields):
    unknown = set(fields) - LISTING_FIELDS
    if unknown:
        raise BlogListingFieldError(
            f"fields outside the link-listing subset are not accepted (D13): {sorted(unknown)}"
        )

    cleaned = {}

    if "title" in fields:
        title = normalize_nfc(fields["title"] or "")
        if not title:
            raise BlogListingFieldError("title must not be empty")
        cleaned["title"] = title

    if "excerpt" in fields:
        cleaned["excerpt"] = normalize_nfc(fields["excerpt"] or "")

    if "canonical_url" in fields:
        cleaned["canonical_url"] = _clean_canonical_url(fields["canonical_url"])

    cover_image_url = _clean_optional_url(fields.get("cover_image_url"), "cover image URL")
    cover_image_alt = normalize_nfc(fields.get("cover_image_alt") or "").strip()
    if cover_image_url and not cover_image_alt:
        raise BlogContentError("cover image alternative text is required")
    if cover_image_alt and not cover_image_url:
        raise BlogContentError("cover image URL is required when alternative text is provided")
    if "cover_image_url" in fields or "cover_image_alt" in fields:
        cleaned["cover_image_url"] = cover_image_url
        cleaned["cover_image_alt"] = cover_image_alt

    if "tags" in fields:
        tags = list(fields["tags"] or [])
        for term in tags:
            if term.vocabulary != TermVocabulary.TAG:
                raise BlogListingFieldError(
                    "blog tags must be taxonomy terms from the TAG vocabulary"
                )
        cleaned["tags"] = tags

    if "language" in fields:
        if fields["language"] not in ContentLanguage.values:
            raise BlogListingFieldError("language must be a supported content language")
        cleaned["language"] = fields["language"]

    if "reading_time_minutes" in fields:
        minutes = fields["reading_time_minutes"]
        if not isinstance(minutes, int) or isinstance(minutes, bool) or minutes < 0:
            raise BlogListingFieldError("reading_time_minutes must be a non-negative integer")
        cleaned["reading_time_minutes"] = minutes

    return cleaned


def _assert_no_official_seal_wording(post):
    for text in (post.title, post.excerpt):
        normalized = normalize_nfc(text or "")
        for phrase in OFFICIAL_SEAL_PHRASES:
            if phrase in normalized:
                raise OfficialSealWordingError(
                    "personal listings must not contain official-seal wording (BR-009)"
                )


def _snapshot(post):
    return {
        "title": post.title,
        "excerpt": post.excerpt,
        "post_type": post.post_type,
        "content_markdown": post.content_markdown,
        "content_rendered": post.content_rendered,
        "canonical_url": post.canonical_url,
        "external_rights_confirmed_at": (
            post.external_rights_confirmed_at.isoformat()
            if post.external_rights_confirmed_at
            else None
        ),
        "cover_image_url": post.cover_image_url,
        "cover_image_alt": post.cover_image_alt,
        "language": post.language,
        "reading_time_minutes": post.reading_time_minutes,
        "official_project_id": post.official_project_id,
        "tags": sorted(post.tags.values_list("slug", flat=True)),
    }


def render_safe_markdown(value):
    """BLG-002/BLG-003: render safe Markdown or raise a typed domain error."""
    try:
        return render_markdown(value)
    except MarkdownValidationError as exc:
        raise BlogContentError(str(exc)) from exc


def _computed_reading_time(value):
    words = re.findall(r"\w+", value, flags=re.UNICODE)
    return max(1, math.ceil(len(words) / 200))


def _clean_native_fields(fields):
    unknown = set(fields) - NATIVE_FIELDS
    if unknown:
        raise BlogListingFieldError(f"unsupported native post fields: {sorted(unknown)}")

    title = normalize_nfc(fields.get("title") or "").strip()
    if not title:
        raise BlogListingFieldError("title must not be empty")
    markdown = normalize_nfc(fields.get("content_markdown") or "").strip()
    if not markdown:
        raise BlogContentError("native posts require Markdown content")
    cover_image_url = _clean_optional_url(fields.get("cover_image_url"), "cover image URL")
    cover_image_alt = normalize_nfc(fields.get("cover_image_alt") or "").strip()
    if cover_image_url and not cover_image_alt:
        raise BlogContentError("cover image alternative text is required")
    if cover_image_alt and not cover_image_url:
        raise BlogContentError("cover image URL is required when alternative text is provided")

    tags = list(fields.get("tags") or [])
    for term in tags:
        if term.vocabulary != TermVocabulary.TAG:
            raise BlogListingFieldError("blog tags must be taxonomy terms from the TAG vocabulary")
    language = fields.get("language", ContentLanguage.ENGLISH)
    if language not in ContentLanguage.values:
        raise BlogListingFieldError("language must be a supported content language")

    return {
        "title": title,
        "excerpt": normalize_nfc(fields.get("excerpt") or ""),
        "content_markdown": markdown,
        "content_rendered": render_safe_markdown(markdown),
        "canonical_url": _clean_optional_url(fields.get("canonical_url"), "canonical URL"),
        "cover_image_url": cover_image_url,
        "cover_image_alt": cover_image_alt,
        "tags": tags,
        "language": language,
        "reading_time_minutes": _computed_reading_time(markdown),
    }


def _record_version(post, actor):
    last = post.versions.order_by("-version_number").first()
    next_number = (last.version_number + 1) if last else 1
    return BlogVersion.objects.create(
        post=post,
        version_number=next_number,
        snapshot=_snapshot(post),
        created_by=actor,
    )


def _apply_fields(post, cleaned):
    for name in (
        "title",
        "excerpt",
        "canonical_url",
        "cover_image_url",
        "cover_image_alt",
        "language",
        "reading_time_minutes",
    ):
        if name in cleaned:
            setattr(post, name, cleaned[name])
    post.save()
    if "tags" in cleaned:
        post.tags.set(cleaned["tags"])


def _holds_active_publisher_role(user):
    assignments = MinistryPublisher.objects.filter(
        user=user,
        status=PublisherStatus.ACTIVE,
    ).select_related("ministry")
    return any(is_publisher_active(user, assignment.ministry) for assignment in assignments)


def can_publish_official(user) -> bool:
    return _holds_active_publisher_role(user)


def _official_project_or_error(author, post, project):
    project_id = getattr(project, "pk", None)
    if project_id is None:
        _deny_official_publication(
            author,
            post,
            OfficialPostProjectError,
            "official publication requires a public ministry project",
        )
    try:
        selected_project = Project.objects.select_related("ministry").get(pk=project_id)
    except Project.DoesNotExist:
        _deny_official_publication(
            author,
            post,
            OfficialPostProjectError,
            "the selected project no longer exists",
        )
    if (
        selected_project.project_type != ProjectType.GOVERNMENT
        or selected_project.status
        not in {
            ProjectStatus.OPEN_FOR_CONTRIBUTION,
            ProjectStatus.PAUSED,
            ProjectStatus.COMPLETED,
        }
        or not is_publisher_active(author, selected_project.ministry)
    ):
        _deny_official_publication(
            author,
            post,
            OfficialPostProjectError,
            "official publication requires a public project from your active ministry assignment",
        )
    return selected_project


def _deny_official_publication(actor, post, error_type, message):
    record_audit(
        actor=actor,
        action="blog.official.denied",
        obj=post,
        before={"status": post.status, "is_official": post.is_official},
        after={"status": post.status, "is_official": post.is_official},
        result="failure",
    )
    logger.warning(
        "BLG-007 official publishing denied for actor=%s post=%s",
        getattr(actor, "pk", None),
        post.pk,
    )
    raise error_type(message)


def create_listing(member, *, external_rights_confirmed_at=None, **fields):
    """BLG-004/BLG-005: a member creates a DRAFT external-link listing (D13: no content copy)."""
    cleaned = _clean_listing_fields(fields)
    if "title" not in fields:
        raise BlogListingFieldError("title is required")
    if "canonical_url" not in fields:
        raise BlogCanonicalUrlError("a canonical URL is required for a link listing")

    post = BlogPost(
        author=member,
        title=cleaned.get("title", ""),
        excerpt=cleaned.get("excerpt", ""),
        canonical_url=cleaned["canonical_url"],
        external_rights_confirmed_at=external_rights_confirmed_at,
        cover_image_url=cleaned.get("cover_image_url", ""),
        cover_image_alt=cleaned.get("cover_image_alt", ""),
        language=cleaned.get("language", ContentLanguage.ENGLISH),
        reading_time_minutes=cleaned.get("reading_time_minutes", 0),
    )
    _assert_no_official_seal_wording(post)

    with transaction.atomic():
        post.save()
        if "tags" in cleaned:
            post.tags.set(cleaned["tags"])
        _record_version(post, member)
        record_audit(
            actor=member,
            action="blog.created",
            obj=post,
            after=_snapshot(post),
        )
    return post


def create_external_article(member, *, rights_confirmed: bool, **fields):
    """BLG-005/MEM-007: persist a link-only external article with confirmed provenance."""
    if rights_confirmed is not True:
        raise BlogProvenanceError("authorship or listing rights must be confirmed")
    fields["canonical_url"] = clean_external_article_url(fields.get("canonical_url"))
    return create_listing(
        member,
        external_rights_confirmed_at=timezone.now(),
        **fields,
    )


def create_native_post(member, **fields):
    """BLG-001/BLG-002/BLG-004: create a checked native Markdown draft."""
    cleaned = _clean_native_fields(fields)
    tags = cleaned.pop("tags")
    post = BlogPost(author=member, post_type=BlogPostType.NATIVE, **cleaned)
    _assert_no_official_seal_wording(post)

    with transaction.atomic():
        post.save()
        post.tags.set(tags)
        _record_version(post, member)
        record_audit(actor=member, action="blog.created", obj=post, after=_snapshot(post))
    return post


def edit_listing(member, post, **fields):
    """BLG-001 (D13 listing subset): the author edits a listing; a BlogVersion snapshot is kept."""
    _require_active_author(member, post)
    if post.post_type != BlogPostType.EXTERNAL:
        raise BlogStateError("a native post cannot be edited as an external article")
    if post.status == BlogStatus.ARCHIVED:
        raise BlogStateError("an archived listing cannot be edited")

    cleaned = _clean_listing_fields(fields)
    for name in (
        "title",
        "excerpt",
        "canonical_url",
        "cover_image_url",
        "cover_image_alt",
        "language",
        "reading_time_minutes",
    ):
        if name in cleaned:
            setattr(post, name, cleaned[name])

    if not post.is_official:
        _assert_no_official_seal_wording(post)

    with transaction.atomic():
        post.save()
        if "tags" in cleaned:
            post.tags.set(cleaned["tags"])
        _record_version(post, member)
        record_audit(
            actor=member,
            action="blog.edited",
            obj=post,
            after=_snapshot(post),
        )
    return post


def edit_native_post(member, post, **fields):
    """BLG-001/BLG-002: edit a native post and retain its checked version snapshot."""
    _require_active_author(member, post)
    if post.post_type != BlogPostType.NATIVE:
        raise BlogStateError("an external article cannot be edited as a native post")
    if post.status == BlogStatus.ARCHIVED:
        raise BlogStateError("an archived post cannot be edited")

    merged = {
        "title": post.title,
        "excerpt": post.excerpt,
        "content_markdown": post.content_markdown,
        "canonical_url": post.canonical_url,
        "cover_image_url": post.cover_image_url,
        "cover_image_alt": post.cover_image_alt,
        "tags": list(post.tags.all()),
        "language": post.language,
    }
    merged.update(fields)
    cleaned = _clean_native_fields(merged)
    tags = cleaned.pop("tags")
    for name, value in cleaned.items():
        setattr(post, name, value)
    if not post.is_official:
        _assert_no_official_seal_wording(post)

    with transaction.atomic():
        post.save()
        post.tags.set(tags)
        _record_version(post, member)
        record_audit(actor=member, action="blog.edited", obj=post, after=_snapshot(post))
    return post


def _prepare_native_for_publication(post):
    if post.post_type != BlogPostType.NATIVE:
        return
    if not post.content_markdown.strip():
        raise BlogContentError("native posts require Markdown content before publication")
    post.content_rendered = render_safe_markdown(post.content_markdown)
    post.reading_time_minutes = _computed_reading_time(post.content_markdown)
    if post.cover_image_url and not post.cover_image_alt.strip():
        raise BlogContentError("cover image alternative text is required before publication")


def publish_listing(member, post):
    """BLG-001 (D13 listing subset): the author publishes a personal link listing."""
    _require_active_author(member, post)
    if post.status not in (BlogStatus.DRAFT, BlogStatus.UNPUBLISHED):
        raise BlogStateError(f"cannot publish a listing in status '{post.status}'")
    if post.is_official:
        raise BlogStateError("official posts are published via publish_official (BLG-007)")

    _assert_no_official_seal_wording(post)

    _prepare_native_for_publication(post)

    with transaction.atomic():
        before = {"status": post.status}
        post.status = BlogStatus.PUBLISHED
        if post.published_at is None:
            post.published_at = timezone.now()
        post.save()
        _record_version(post, member)
        record_audit(
            actor=member,
            action="blog.published",
            obj=post,
            before=before,
            after={"status": post.status, "published_at": post.published_at.isoformat()},
        )
    return post


def publish_official(author, post, *, project=None):
    """BLG-007: official publishing needs an active publisher role; sets the label contract."""
    if (
        author is None
        or not getattr(author, "is_active", False)
        or not getattr(author, "is_authenticated", False)
        or author != post.author
    ):
        _deny_official_publication(
            author,
            post,
            BlogOwnershipError,
            "only the active author may publish an official post",
        )
    if post.status not in (BlogStatus.DRAFT, BlogStatus.UNPUBLISHED):
        _deny_official_publication(
            author,
            post,
            BlogStateError,
            f"cannot officially publish a listing in status '{post.status}'",
        )
    if post.moderation_state not in (
        BlogModerationState.NOT_REVIEWED,
        BlogModerationState.REINSTATED,
    ):
        _deny_official_publication(
            author,
            post,
            BlogStateError,
            "a post under moderation cannot be officially published",
        )
    if not _holds_active_publisher_role(author):
        _deny_official_publication(
            author,
            post,
            OfficialPostPermissionError,
            "official publishing requires an active ministry publisher role",
        )
    selected_project = _official_project_or_error(author, post, project)
    require_privileged_mfa(
        author,
        action="blog.official",
        obj=post,
        error_type=OfficialPostPermissionError,
    )
    _prepare_native_for_publication(post)

    with transaction.atomic():
        before = {
            "status": post.status,
            "is_official": post.is_official,
            "official_project_id": post.official_project_id,
        }
        post.is_official = True
        post.official_published_by = author
        post.official_project = selected_project
        post.status = BlogStatus.PUBLISHED
        if post.published_at is None:
            post.published_at = timezone.now()
        post.save()
        _record_version(post, author)
        record_audit(
            actor=author,
            action="blog.published.official",
            obj=post,
            before=before,
            after={
                "status": post.status,
                "is_official": post.is_official,
                "official_published_by": author.username,
                "official_project_id": selected_project.pk,
            },
        )
    return post


def unpublish(member, post):
    """BLG-001 (D13 listing subset): the author unpublishes a published listing."""
    _require_active_author(member, post)
    if post.status != BlogStatus.PUBLISHED:
        raise BlogStateError(f"cannot unpublish a listing in status '{post.status}'")

    with transaction.atomic():
        before = {"status": post.status}
        post.status = BlogStatus.UNPUBLISHED
        post.save()
        _record_version(post, member)
        record_audit(
            actor=member,
            action="blog.unpublished",
            obj=post,
            before=before,
            after={"status": post.status},
        )
    return post


def archive(member, post):
    """BLG-001 (D13 listing subset): the author archives a listing."""
    _require_active_author(member, post)
    if post.status == BlogStatus.ARCHIVED:
        raise BlogStateError("listing is already archived")

    with transaction.atomic():
        before = {"status": post.status}
        post.status = BlogStatus.ARCHIVED
        post.save()
        _record_version(post, member)
        record_audit(
            actor=member,
            action="blog.archived",
            obj=post,
            before=before,
            after={"status": post.status},
        )
    return post


def _transition_moderation(actor, post, to_state, *, action):
    allowed = MODERATION_TRANSITIONS.get(post.moderation_state, frozenset())
    if to_state not in allowed:
        raise BlogModerationTransitionError(
            f"cannot move a '{post.moderation_state}' post to '{to_state}'"
        )

    with transaction.atomic():
        before = {"moderation_state": post.moderation_state, "status": post.status}
        post.moderation_state = to_state
        post.save()
        record_audit(
            actor=actor,
            action=action,
            obj=post,
            before=before,
            after={"moderation_state": post.moderation_state, "status": post.status},
        )
    return post


def flag_post(actor, post):
    """BLG-006: a report flags the post into moderation review (UNDER_REVIEW)."""
    return _transition_moderation(
        actor, post, BlogModerationState.UNDER_REVIEW, action="blog.moderation.flagged"
    )


def restrict_post(actor, post):
    """BLG-006: a moderator restricts (removes from public view) a reviewed post."""
    return _transition_moderation(
        actor, post, BlogModerationState.RESTRICTED, action="blog.moderation.restricted"
    )


def reinstate_post(actor, post):
    """BLG-006: a moderator reinstates a restricted post after review or appeal."""
    return _transition_moderation(
        actor, post, BlogModerationState.REINSTATED, action="blog.moderation.reinstated"
    )
