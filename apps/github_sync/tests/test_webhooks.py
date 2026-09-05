import hashlib
import hmac

import pytest

from apps.github_sync.enums import VerifiedEventKind
from apps.github_sync.webhooks import parse_event, verify_signature

pytestmark = [pytest.mark.unit, pytest.mark.github_webhook]

SECRET = "webhook-test-secret-0123456789abcdef"
KNOWN_BODY = b'{"action":"closed"}'
KNOWN_SIGNATURE = "sha256=8f656a2d5cd9f850ae448dd0bc31b47f470d8e04ef5d570b1d852ea4903083cf"


class TestVerifiedEventKindEnum:
    def test_enum_contains_exactly_d7_verified_kinds(self):
        """D7/GIT-007: verified kinds are PR merged, issue completed, approved review, release."""
        assert {choice.value for choice in VerifiedEventKind} == {
            "pr_merged",
            "issue_completed",
            "review_approved",
            "release_published",
        }

    def test_enum_excludes_raw_commit_kinds(self):
        """D7/GIT-008: raw/direct commit kinds are excluded from verified events entirely."""
        values = " ".join(choice.value for choice in VerifiedEventKind).lower()
        assert "commit" not in values
        assert "push" not in values


class TestVerifySignature:
    def test_accepts_known_vector(self):
        """GIT-004: a correctly computed HMAC-SHA256 signature over a known vector is accepted."""
        assert verify_signature(SECRET, KNOWN_BODY, KNOWN_SIGNATURE)

    def test_accepts_uppercase_hex_digest(self):
        """GIT-004: a valid signature with uppercase hex encoding is still accepted."""
        assert verify_signature(SECRET, KNOWN_BODY, KNOWN_SIGNATURE.upper())

    def test_rejects_tampered_body(self):
        """GIT-004: a signature valid for the original body is rejected when body is modified."""
        assert not verify_signature(SECRET, b'{"action":"reopened"}', KNOWN_SIGNATURE)

    def test_rejects_wrong_secret(self):
        """GIT-004: signatures computed with a different secret are rejected."""
        forged = hmac.new(b"attacker-secret", KNOWN_BODY, hashlib.sha256).hexdigest()
        assert not verify_signature(SECRET, KNOWN_BODY, f"sha256={forged}")

    def test_rejects_wrong_prefix(self):
        """GIT-004: signatures not using the sha256= prefix (e.g. sha1=) are rejected."""
        digest = KNOWN_SIGNATURE.removeprefix("sha256=")
        assert not verify_signature(SECRET, KNOWN_BODY, f"sha1={digest}")

    def test_rejects_missing_header(self):
        """GIT-004: a delivery without a signature header is rejected, never processed."""
        assert not verify_signature(SECRET, KNOWN_BODY, None)
        assert not verify_signature(SECRET, KNOWN_BODY, "")

    def test_rejects_malformed_header(self):
        """GIT-004: malformed signature headers (no digest, non-hex digest) are rejected."""
        assert not verify_signature(SECRET, KNOWN_BODY, "sha256=")
        assert not verify_signature(SECRET, KNOWN_BODY, "sha256=not-hex-at-all")
        bare = KNOWN_SIGNATURE.removeprefix("sha256=")
        assert not verify_signature(SECRET, KNOWN_BODY, bare)


def pr_payload(
    action="closed",
    merged=True,
    login="cdjk",
    actor_type="User",
    author_login=None,
    author_type=None,
):
    return {
        "action": action,
        "pull_request": {
            "id": 987654,
            "number": 42,
            "merged": merged,
            "user": {"login": author_login or login, "type": author_type or actor_type},
        },
        "repository": {"id": 555, "node_id": "R_kgDOKExAmPlE", "name": "gov-portal"},
        "sender": {"login": login, "type": actor_type},
    }


def issue_payload(state_reason="completed", login="sita", actor_type="User"):
    issue = {"id": 1234, "number": 7, "state": "closed", "state_reason": state_reason}
    return {
        "action": "closed",
        "issue": issue,
        "repository": {"id": 555, "node_id": "R_kgDOKExAmPlE", "name": "gov-portal"},
        "sender": {"login": login, "type": actor_type},
    }


def review_payload(review_state="approved", action="submitted", login="rama", actor_type="User"):
    return {
        "action": action,
        "review": {"id": 4321, "state": review_state},
        "pull_request": {"id": 987654, "number": 42, "merged": False},
        "repository": {"id": 555, "node_id": "R_kgDOKExAmPlE", "name": "gov-portal"},
        "sender": {"login": login, "type": actor_type},
    }


def release_payload(action="published", login="hari", actor_type="User"):
    return {
        "action": action,
        "release": {"id": 7777, "tag_name": "v1.0.0"},
        "repository": {"id": 555, "node_id": "R_kgDOKExAmPlE", "name": "gov-portal"},
        "sender": {"login": login, "type": actor_type},
    }


class TestParseEvent:
    def test_pull_request_closed_and_merged_is_pr_merged(self):
        """GIT-007/D7: pull_request closed with merged=true maps to PR_MERGED with provenance."""
        parsed = parse_event("pull_request", pr_payload())
        assert parsed is not None
        assert parsed.kind == VerifiedEventKind.PR_MERGED
        assert parsed.action == "closed"
        assert parsed.actor_login == "cdjk"
        assert parsed.triggered_by_login == "cdjk"
        assert parsed.repository_node_id == "R_kgDOKExAmPlE"
        assert parsed.repository_name == "gov-portal"
        assert parsed.number == 42
        assert parsed.event_id == "987654"
        assert parsed.is_bot is False

    def test_merged_pull_request_credits_author_not_merging_sender(self):
        """GIT-007/D7: a merged PR credits its author while retaining the merger provenance."""
        parsed = parse_event(
            "pull_request",
            pr_payload(login="maintainer", author_login="contributor"),
        )

        assert parsed is not None
        assert parsed.actor_login == "contributor"
        assert parsed.triggered_by_login == "maintainer"

    def test_merged_pull_request_filters_bot_author_even_when_merged_by_a_human(self):
        """GIT-008: contribution bot filtering follows the PR author, not the merge actor."""
        parsed = parse_event(
            "pull_request",
            pr_payload(login="maintainer", author_login="dependabot[bot]"),
        )

        assert parsed is not None
        assert parsed.actor_login == "dependabot[bot]"
        assert parsed.triggered_by_login == "maintainer"
        assert parsed.is_bot is True

    def test_pull_request_closed_unmerged_is_ignored(self):
        """GIT-007/D7: pull_request closed without a merge produces no verified event."""
        assert parse_event("pull_request", pr_payload(merged=False)) is None

    def test_pull_request_reopened_is_ignored(self):
        """GIT-007: only the closed+merged transition qualifies; other PR actions are ignored."""
        assert parse_event("pull_request", pr_payload(action="reopened")) is None

    def test_issues_closed_completed_is_issue_completed(self):
        """GIT-007/D7: issues closed with state_reason completed maps to ISSUE_COMPLETED."""
        parsed = parse_event("issues", issue_payload())
        assert parsed is not None
        assert parsed.kind == VerifiedEventKind.ISSUE_COMPLETED
        assert parsed.number == 7
        assert parsed.event_id == "1234"
        assert parsed.actor_login == "sita"

    def test_issues_closed_not_planned_is_ignored(self):
        """GIT-007/D7: issues closed as not_planned are not completed work and are ignored."""
        assert parse_event("issues", issue_payload(state_reason="not_planned")) is None

    def test_issues_opened_is_ignored(self):
        """GIT-007: non-closed issue actions produce no verified event."""
        payload = issue_payload()
        payload["action"] = "opened"
        assert parse_event("issues", payload) is None

    def test_review_submitted_approved_is_review_approved(self):
        """GIT-007/D7: pull_request_review submitted with state approved maps to REVIEW_APPROVED."""
        parsed = parse_event("pull_request_review", review_payload())
        assert parsed is not None
        assert parsed.kind == VerifiedEventKind.REVIEW_APPROVED
        assert parsed.event_id == "4321"
        assert parsed.number == 42
        assert parsed.actor_login == "rama"

    def test_review_changes_requested_is_ignored(self):
        """GIT-007: reviews that are not approvals (changes_requested, commented) are ignored."""
        non_approval = review_payload(review_state="changes_requested")
        assert parse_event("pull_request_review", non_approval) is None
        commented = review_payload(review_state="commented")
        assert parse_event("pull_request_review", commented) is None

    def test_review_dismissed_is_ignored(self):
        """GIT-007/D7: a dismissed review (dismissed=false requirement violated) never qualifies."""
        assert parse_event("pull_request_review", review_payload(action="dismissed")) is None

    def test_release_published_is_release_published(self):
        """GIT-007/D7: release published maps to RELEASE_PUBLISHED."""
        parsed = parse_event("release", release_payload())
        assert parsed is not None
        assert parsed.kind == VerifiedEventKind.RELEASE_PUBLISHED
        assert parsed.event_id == "7777"
        assert parsed.number is None
        assert parsed.actor_login == "hari"

    def test_release_updated_and_deleted_are_ignored(self):
        """GIT-007: only the published release action qualifies."""
        assert parse_event("release", release_payload(action="updated")) is None
        assert parse_event("release", release_payload(action="deleted")) is None

    def test_push_event_is_ignored(self):
        """D7/GIT-008: raw push/commit events are excluded entirely, no credit."""
        payload = {
            "action": None,
            "repository": {"id": 555, "node_id": "R_kgDOKExAmPlE", "name": "gov-portal"},
            "sender": {"login": "cdjk", "type": "User"},
        }
        assert parse_event("push", payload) is None

    def test_unlisted_event_is_ignored(self):
        """GIT-007: event types outside the configured set produce no verified activity."""
        assert parse_event("star", release_payload()) is None

    def test_bot_login_suffix_is_flagged(self):
        """GIT-008: bot actors (login ending in [bot]) are flagged, never credit."""
        parsed = parse_event("pull_request", pr_payload(login="dependabot[bot]", actor_type="User"))
        assert parsed is not None
        assert parsed.is_bot is True

    def test_bot_actor_type_is_flagged(self):
        """GIT-008: actors with type Bot are flagged regardless of login suffix."""
        parsed = parse_event("pull_request", pr_payload(login="gov-portal-ci", actor_type="Bot"))
        assert parsed is not None
        assert parsed.is_bot is True

    def test_bot_flag_still_parses_kind_for_ledger(self):
        """GIT-008/GIT-012: bot events keep provenance so they are recorded without credit."""
        parsed = parse_event("issues", issue_payload(login="renovate[bot]"))
        assert parsed is not None
        assert parsed.is_bot is True
        assert parsed.kind == VerifiedEventKind.ISSUE_COMPLETED

    def test_payload_missing_core_objects_is_ignored(self):
        """GIT-007: malformed payloads without the event object are ignored rather than crashing."""
        bare_pr = {"action": "closed", "sender": {"login": "x", "type": "User"}}
        assert parse_event("pull_request", bare_pr) is None
        assert parse_event("issues", {"action": "closed"}) is None
