import pytest

from apps.github_sync.webhooks import dedup_keys

pytestmark = [pytest.mark.unit, pytest.mark.github_webhook]

PROVIDER = "github"
DELIVERY_ID = "72d3162e-cc78-11e3-81ab-4c9367dc0958"
EVENT_ID = "987654"


class TestDedupKeys:
    def test_returns_both_delivery_and_event_keys(self):
        """GIT-005: dedup keys include (provider, delivery_id) and (provider, event_id)."""
        keys = dedup_keys(PROVIDER, DELIVERY_ID, EVENT_ID)
        assert keys.delivery_key == ("github", DELIVERY_ID)
        assert keys.event_key == ("github", EVENT_ID)

    def test_keys_are_provider_scoped(self):
        """GIT-012/D6: both dedup keys are scoped by provider so future providers cannot collide."""
        keys = dedup_keys(PROVIDER, DELIVERY_ID, EVENT_ID)
        assert all(key[0] == "github" for key in (keys.delivery_key, keys.event_key))

    def test_same_delivery_yields_identical_delivery_key(self):
        """GIT-005/A5: the same delivery GUID maps to the same key (idempotency)."""
        first = dedup_keys(PROVIDER, DELIVERY_ID, EVENT_ID)
        second = dedup_keys(PROVIDER, DELIVERY_ID, "different-event-id")
        assert first.delivery_key == second.delivery_key

    def test_same_event_different_delivery_yields_identical_event_key(self):
        """GIT-005/D6: the same provider event under a new delivery is caught by the second key."""
        first = dedup_keys(PROVIDER, DELIVERY_ID, EVENT_ID)
        second = dedup_keys(PROVIDER, "0f0a2b40-new-delivery-guid", EVENT_ID)
        assert first.delivery_key != second.delivery_key
        assert first.event_key == second.event_key

    def test_result_is_a_plain_tuple_of_keys(self):
        """GIT-005: dedup_keys returns both keys as a tuple usable by the persistence layer."""
        keys = dedup_keys(PROVIDER, DELIVERY_ID, EVENT_ID)
        assert tuple(keys) == (
            ("github", DELIVERY_ID),
            ("github", EVENT_ID),
        )
