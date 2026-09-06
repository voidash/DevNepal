import logging
import os
from collections.abc import Sequence

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)

logger = logging.getLogger("apps.observability.tracing")

_configured = False


class JsonLogSpanExporter(SpanExporter):
    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        for span in spans:
            context = span.get_span_context()
            parent_span_id = f"{span.parent.span_id:016x}" if span.parent else ""
            logger.info(
                "trace.completed",
                extra={
                    "trace_id": f"{context.trace_id:032x}",
                    "span_id": f"{context.span_id:016x}",
                    "parent_span_id": parent_span_id,
                    "span_name": span.name,
                    "span_status": span.status.status_code.name.lower(),
                    "duration_seconds": (span.end_time - span.start_time) / 1_000_000_000,
                },
            )
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None


def configure_tracing() -> None:
    global _configured
    if _configured:
        return
    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: "devnepal"}))
    provider.add_span_processor(SimpleSpanProcessor(JsonLogSpanExporter()))
    endpoint = os.environ.get("OBSERVABILITY_OTLP_TRACES_ENDPOINT", "")
    if endpoint:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    _configured = True


def current_trace_fields() -> dict[str, str]:
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return {}
    return {"trace_id": f"{context.trace_id:032x}", "span_id": f"{context.span_id:016x}"}
