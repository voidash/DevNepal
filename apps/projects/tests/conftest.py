import tempfile

from django.conf import settings

settings.MEDIA_ROOT = tempfile.mkdtemp(prefix="devnepal-projects-tests-")
