import hmac
import logging
import os

from django.conf import settings
from django.db import connection
from django.db.utils import Error as DatabaseLayerError
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_GET
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, generate_latest

from apps.observability.metrics import refresh_db_backed_gauges

logger = logging.getLogger(__name__)


@require_GET
def healthz(request):
    """Liveness: this process is up and can serve a response. No dependency checks."""
    return JsonResponse({"status": "ok"})


@require_GET
def readyz(request):
    """Readiness: this process can serve real traffic (NFR-AVL-02)."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseLayerError:
        logger.exception("readyz: database check failed")
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ready"})


def _metrics_authorized(request) -> bool:
    expected = getattr(settings, "OBSERVABILITY_METRICS_TOKEN", "")
    if not expected:
        return False
    provided = request.META.get("HTTP_AUTHORIZATION", "")
    prefix = "Bearer "
    if not provided.startswith(prefix):
        return False
    return hmac.compare_digest(provided[len(prefix) :], expected)


@require_GET
def metrics(request):
    """Prometheus exposition endpoint. Requires a bearer token (public gov portal)."""
    if not _metrics_authorized(request):
        return HttpResponse(status=403)

    refresh_db_backed_gauges()

    multiproc_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if multiproc_dir:
        from prometheus_client import multiprocess

        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        payload = generate_latest(registry)
    else:
        payload = generate_latest()

    return HttpResponse(payload, content_type=CONTENT_TYPE_LATEST)
