from datetime import UTC, datetime, timedelta

import pytest

from apps.github_sync.webhooks import is_within_replay_window

pytestmark = [pytest.mark.unit, pytest.mark.github_webhook]

NOW = datetime(2026, 9, 3, 12, 0, 0, tzinfo=UTC)


class TestReplayWindow:
    def test_absent_timestamp_is_accepted_for_github_app_webhooks(self):
        """GIT-005: real App deliveries have no timestamp header; dedup + signature protect."""
        assert is_within_replay_window(None, NOW)
        assert is_within_replay_window("", NOW)
        assert is_within_replay_window("   ", NOW)

    def test_fresh_rfc3339_timestamp_accepted(self):
        """GIT-005: a delivery timestamp inside the replay window is accepted."""
        header = "2026-09-03T11:58:00Z"
        assert is_within_replay_window(header, NOW)

    def test_stale_timestamp_rejected(self):
        """GIT-005: replayed deliveries older than the window are rejected."""
        header = "2026-09-03T11:00:00Z"
        assert not is_within_replay_window(header, NOW)

    def test_future_timestamp_beyond_skew_rejected(self):
        """GIT-005: timestamps from the far future (clock skew / replay probe) are rejected."""
        header = "2026-09-03T12:30:00Z"
        assert not is_within_replay_window(header, NOW)

    def test_window_boundary_is_inclusive(self):
        """GIT-005: the window is inclusive at max_skew_seconds and rejects one second past it."""
        boundary = NOW - timedelta(seconds=300)
        assert is_within_replay_window(boundary.isoformat(), NOW)
        past = NOW - timedelta(seconds=301)
        assert not is_within_replay_window(past.isoformat(), NOW)

    def test_future_inside_skew_accepted(self):
        """GIT-005: small future skew within the window is tolerated (clock drift)."""
        header = (NOW + timedelta(seconds=120)).isoformat()
        assert is_within_replay_window(header, NOW)

    def test_rfc3339_with_numeric_offset_accepted(self):
        """GIT-005: RFC3339 timestamps with a numeric UTC offset are parsed correctly."""
        assert is_within_replay_window("2026-09-03T17:43:00+05:45", NOW)

    def test_unix_epoch_timestamp_accepted(self):
        """GIT-005: Unix epoch timestamps are accepted when fresh."""
        epoch = int((NOW - timedelta(seconds=60)).timestamp())
        assert is_within_replay_window(str(epoch), NOW)

    def test_unix_epoch_timestamp_stale_rejected(self):
        """GIT-005: stale Unix epoch timestamps are rejected as replays."""
        epoch = int((NOW - timedelta(hours=2)).timestamp())
        assert not is_within_replay_window(str(epoch), NOW)

    def test_malformed_timestamp_rejected(self):
        """GIT-005: unparseable timestamp values are rejected rather than guessed."""
        assert not is_within_replay_window("not-a-timestamp", NOW)
        assert not is_within_replay_window("2026-13-45T99:99:99Z", NOW)
        assert not is_within_replay_window("99999999999999999999", NOW)

    def test_naive_now_treated_as_utc(self):
        """GIT-005: a naive `now` is interpreted as UTC (USE_TZ convention), not crashing."""
        naive_now = datetime(2026, 9, 3, 12, 0, 0)
        assert is_within_replay_window("2026-09-03T11:59:00Z", naive_now)

    def test_custom_skew_window_is_honored(self):
        """GIT-005: the clock-skew window is configurable and enforced."""
        header = "2026-09-03T11:50:00Z"
        assert not is_within_replay_window(header, NOW, max_skew_seconds=300)
        assert is_within_replay_window(header, NOW, max_skew_seconds=900)
