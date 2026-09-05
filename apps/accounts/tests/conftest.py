import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def isolate_account_rate_limit_cache():
    """SEC-006: account tests do not share process-wide throttle counters."""
    cache.clear()
    yield
    cache.clear()
