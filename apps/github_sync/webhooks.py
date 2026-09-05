import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import NamedTuple

from apps.github_sync.enums import VerifiedEventKind

SIGNATURE_PREFIX = "sha256="
DEFAULT_MAX_SKEW_SECONDS = 300
ISSUE_LIFECYCLE_ACTIONS = frozenset(
    {"opened", "edited", "reopened", "closed", "labeled", "unlabeled", "deleted"}
)


class DedupKeys(NamedTuple):
    """D6: both webhook deduplication keys — delivery GUID key first, provider event id second."""

    delivery_key: tuple[str, str]
    event_key: tuple[str, str]


@dataclass(frozen=True)
class ParsedEvent:
    """GIT-012: normalized provenance extracted from a verified webhook payload."""

    kind: VerifiedEventKind
    action: str
    actor_login: str
    actor_type: str
    is_bot: bool
    repository_node_id: str
    repository_name: str
    number: int | None
    event_id: str
    triggered_by_login: str = ""


@dataclass(frozen=True)
class ParsedIssueLifecycleEvent:
    """GIT-003/GIT-005: minimal signed issue change data needed to refresh a projection."""

    action: str
    repository_node_id: str


def verify_signature(secret: str, payload_body: bytes, signature_header: str | None) -> bool:
    """GIT-004: validate an X-Hub-Signature-256 header against the raw body in constant time."""
    normalized = signature_header.lower() if signature_header else ""
    if not normalized.startswith(SIGNATURE_PREFIX):
        return False
    provided = normalized.removeprefix(SIGNATURE_PREFIX).strip()
    expected = hmac.new(secret.encode("utf-8"), payload_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided)


def dedup_keys(provider: str, delivery_id: str, event_id: str) -> DedupKeys:
    """D6/GIT-005: build both idempotency keys, delivery first and provider event second."""
    return DedupKeys((provider, delivery_id), (provider, event_id))


def parse_event(event: str, payload: dict) -> ParsedEvent | None:
    """GIT-007/D7: map a webhook event to a verified kind, or None when it earns no credit."""
    action = payload.get("action")
    sender = payload.get("sender") or {}
    repository = payload.get("repository") or {}
    actor_login = sender.get("login", "")

    def parsed(kind, number, event_id, *, credited_actor=None):
        credited_actor = credited_actor or sender
        credited_login = credited_actor.get("login", "")
        credited_type = credited_actor.get("type", "")
        return ParsedEvent(
            kind=kind,
            action=action or "",
            actor_login=credited_login,
            actor_type=credited_type,
            is_bot=credited_login.endswith("[bot]") or credited_type == "Bot",
            repository_node_id=repository.get("node_id", ""),
            repository_name=repository.get("name", ""),
            number=number,
            event_id=str(event_id),
            triggered_by_login=actor_login,
        )

    if event == "pull_request" and action == "closed":
        pull_request = payload.get("pull_request") or {}
        if pull_request.get("id") is None:
            return None
        if pull_request.get("merged") is True:
            number = pull_request.get("number")
            return parsed(
                VerifiedEventKind.PR_MERGED,
                number,
                pull_request["id"],
                credited_actor=pull_request.get("user"),
            )
        return None

    if event == "issues" and action == "closed":
        issue = payload.get("issue") or {}
        if issue.get("id") is None:
            return None
        if issue.get("state_reason", "completed") == "completed":
            return parsed(VerifiedEventKind.ISSUE_COMPLETED, issue.get("number"), issue["id"])
        return None

    if event == "pull_request_review" and action == "submitted":
        review = payload.get("review") or {}
        pull_request = payload.get("pull_request") or {}
        if review.get("id") is None or review.get("state") != "approved":
            return None
        return parsed(VerifiedEventKind.REVIEW_APPROVED, pull_request.get("number"), review["id"])

    if event == "release" and action == "published":
        release = payload.get("release") or {}
        if release.get("id") is None:
            return None
        return parsed(VerifiedEventKind.RELEASE_PUBLISHED, None, release["id"])

    return None


def parse_issue_lifecycle_event(event: str, payload: dict) -> ParsedIssueLifecycleEvent | None:
    """GIT-003/GIT-005: recognize issue changes that invalidate a public repository cache."""
    if event != "issues":
        return None
    action = payload.get("action")
    if action not in ISSUE_LIFECYCLE_ACTIONS:
        return None
    issue = payload.get("issue") or {}
    repository = payload.get("repository") or {}
    try:
        issue_id = int(issue["id"])
        issue_number = int(issue["number"])
    except (KeyError, TypeError, ValueError):
        return None
    repository_node_id = str(repository.get("node_id") or "").strip()
    if issue_id < 1 or issue_number < 1 or not repository_node_id:
        return None
    return ParsedIssueLifecycleEvent(action=action, repository_node_id=repository_node_id)


def is_within_replay_window(
    timestamp_header: str | None,
    now: datetime,
    max_skew_seconds: int = DEFAULT_MAX_SKEW_SECONDS,
) -> bool:
    """GIT-005: enforce a delivery timestamp when the provider supplies one.

    GitHub App webhooks carry no delivery-timestamp header; for those the
    signature check plus the delivery-GUID unique constraint are the replay
    defenses, so an absent header is accepted. When a header IS supplied
    (e.g. a trusted relay), it must fall inside the skew window.
    """
    if not timestamp_header or not timestamp_header.strip():
        return True
    delivered_at = _parse_timestamp(timestamp_header.strip())
    if delivered_at is None:
        return False
    if delivered_at.tzinfo is None:
        delivered_at = delivered_at.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return abs((now - delivered_at).total_seconds()) <= max_skew_seconds


def _parse_timestamp(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        pass
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (ValueError, OverflowError, OSError):
        return None
