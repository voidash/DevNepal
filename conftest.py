import pytest
from django.conf import settings
from django.utils import translation


@pytest.fixture(autouse=True)
def _reset_thread_language():
    """NFR-I18N-01: isolate per-request locale state between tests.

    django.views.i18n.set_language activates the chosen language for the
    worker thread; without a reset, tests that switch to Nepali leak that
    activation into every later test in the same process, making failures
    depend on collection order.
    """
    translation.activate(settings.LANGUAGE_CODE)
    yield
    translation.deactivate()
