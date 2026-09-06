import time

from django.conf import settings
from django.db import connection
from opentelemetry import trace
from opentelemetry.propagate import extract, inject
from opentelemetry.trace import SpanKind, Status, StatusCode

from apps.observability.context import (
    CORRELATION_ID_HEADER,
    CORRELATION_ID_RESPONSE_HEADER,
    is_valid_correlation_id,
    new_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)
from apps.observability.metrics import (
    DB_QUERIES_PER_REQUEST,
    DB_QUERIES_TOTAL,
    DB_QUERY_DURATION_SECONDS,
    HTTP_REQUEST_DURATION_SECONDS,
    HTTP_REQUESTS_IN_PROGRESS,
    HTTP_REQUESTS_TOTAL,
    HTTP_USER_REQUESTS_TOTAL,
    is_user_facing_route,
)


class CorrelationIdMiddleware:
    """NFR-OBS-01: add a trusted correlation context, trace, and RED measurements."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        inbound = request.META.get(CORRELATION_ID_HEADER, "")
        trusted_correlation = getattr(
            settings, "OBSERVABILITY_TRUST_INBOUND_CORRELATION_IDS", False
        )
        correlation_id = (
            inbound
            if trusted_correlation and is_valid_correlation_id(inbound)
            else new_correlation_id()
        )
        trace_context = extract(request.META) if trusted_correlation else None
        set_correlation_id(correlation_id)
        try:
            tracer = trace.get_tracer("devnepal.http")
            with tracer.start_as_current_span(
                "http.request", context=trace_context, kind=SpanKind.SERVER
            ) as span:
                HTTP_REQUESTS_IN_PROGRESS.inc()
                started_at = time.monotonic()
                try:
                    response = self.get_response(request)
                finally:
                    HTTP_REQUESTS_IN_PROGRESS.dec()
                duration = time.monotonic() - started_at

                resolver_match = getattr(request, "resolver_match", None)
                route = resolver_match.route if resolver_match is not None else "unmatched"
                status = str(response.status_code)
                span.set_attribute("http.request.method", request.method)
                span.set_attribute("http.route", route)
                span.set_attribute("http.response.status_code", response.status_code)
                if response.status_code >= 500:
                    span.set_status(Status(StatusCode.ERROR, "server_error"))
                HTTP_REQUESTS_TOTAL.labels(method=request.method, route=route, status=status).inc()
                if is_user_facing_route(route):
                    HTTP_USER_REQUESTS_TOTAL.labels(
                        method=request.method, route=route, status=status
                    ).inc()
                HTTP_REQUEST_DURATION_SECONDS.labels(method=request.method, route=route).observe(
                    duration
                )

                response[CORRELATION_ID_RESPONSE_HEADER] = correlation_id
                trace_headers: dict[str, str] = {}
                inject(trace_headers)
                if traceparent := trace_headers.get("traceparent"):
                    response["traceparent"] = traceparent
                return response
        finally:
            reset_correlation_id()


class DatabaseMetricsMiddleware:
    """NFR-OBS-01: per-request database query count, latency, and error outcome.

    Wraps every SQL execution on the default connection via Django's
    `execute_wrapper` hook, independent of `DEBUG` (unlike
    `connection.queries`, which only records when `DEBUG=True`).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        query_count = 0

        def wrapper(execute, sql, params, many, context):
            nonlocal query_count
            query_count += 1
            alias = context["connection"].alias
            started_at = time.monotonic()
            try:
                result = execute(sql, params, many, context)
            except Exception:
                DB_QUERIES_TOTAL.labels(alias=alias, outcome="error").inc()
                raise
            else:
                DB_QUERIES_TOTAL.labels(alias=alias, outcome="success").inc()
                return result
            finally:
                DB_QUERY_DURATION_SECONDS.labels(alias=alias).observe(time.monotonic() - started_at)

        with connection.execute_wrapper(wrapper):
            response = self.get_response(request)
        DB_QUERIES_PER_REQUEST.observe(query_count)
        return response
