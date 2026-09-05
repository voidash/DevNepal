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
PULL_REQUEST_LIFECYCLE_ACTIONS = frozenset(
    {
        "opened",
        "edited",
        "reopened",
        "closed",
        "ready_for_review",
        "converted_to_draft",
        "labeled",
        "unlabeled",
    }
)
ISSUE_COMMENT_LIFECYCLE_ACTIONS = frozenset({"created", "edited", "deleted"})


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
class ParsedPublicSnapshotLifecycleEvent:
    """GIT-003/GIT-005: minimal signed cache-invalidation data from a webhook."""

    action: str
    repository_node_id: str
    snapshot_item: dict


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


def parse_public_snapshot_lifecycle_event(
    event: str, payload: dict
) -> ParsedPublicSnapshotLifecycleEvent | None:
    """GIT-003/GIT-005: recognize signed changes that invalidate public projections."""
    actions = {
        "issues": ISSUE_LIFECYCLE_ACTIONS,
        "pull_request": PULL_REQUEST_LIFECYCLE_ACTIONS,
        "issue_comment": ISSUE_COMMENT_LIFECYCLE_ACTIONS,
    }.get(event)
    if actions is None:
        return None
    action = payload.get("action")
    if action not in actions:
        return None
    subject_key = "pull_request" if event == "pull_request" else "issue"
    subject = payload.get(subject_key) or {}
    if event == "issue_comment" and not isinstance(payload.get("comment"), dict):
        return None
    repository = payload.get("repository") or {}
    try:
        subject_id = int(subject["id"])
        subject_number = int(subject["number"])
    except (KeyError, TypeError, ValueError):
        return None
    repository_node_id = str(repository.get("node_id") or "").strip()
    if subject_id < 1 or subject_number < 1 or not repository_node_id:
        return None
    return ParsedPublicSnapshotLifecycleEvent(
        action=action,
        repository_node_id=repository_node_id,
        snapshot_item=_bounded_snapshot_item(subject),
    )


def _bounded_snapshot_item(subject: dict) -> dict:
    """GIT-010: retain only bounded public fields needed for immediate projection."""
    user = subject.get("user") if isinstance(subject.get("user"), dict) else {}
    labels = subject.get("labels") if isinstance(subject.get("labels"), list) else []
    return {
        "id": subject.get("id"),
        "number": subject.get("number"),
        "title": str(subject.get("title") or "")[:301],
        "body": str(subject.get("body") or "")[:10_000],
        "state": str(subject.get("state") or ""),
        "comments": subject.get("comments", 0),
        "html_url": str(subject.get("html_url") or "")[:500],
        "updated_at": str(subject.get("updated_at") or "")[:100],
        "user": {
            "login": str(user.get("login") or "")[:101],
            "avatar_url": str(user.get("avatar_url") or "")[:500],
        },
        "labels": [
            {"name": str(label.get("name") or "")[:101]}
            for label in labels[:21]
            if isinstance(label, dict)
        ],
        **({"pull_request": True} if "pull_request" in subject else {}),
    }


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
