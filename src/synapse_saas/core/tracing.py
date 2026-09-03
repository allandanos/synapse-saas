"""OpenTelemetry tracing setup.

Zero-config default: a no-op tracer provider — code can emit spans anywhere
without an exporter shipping anything. Configure SYNAPSE_OTEL_EXPORTER_ENDPOINT
to send spans over OTLP gRPC to a collector (Tempo, Jaeger, Honeycomb, …).

Trace correlation: the request middleware injects the current trace_id into
structlog context and problem documents — a 4xx/5xx response carries the same
trace id your APM shows.
"""

from __future__ import annotations

from typing import Any

from synapse_saas.core.config import get_settings
from synapse_saas.core.logging import get_logger

logger = get_logger(__name__)

_configured = False


def configure_tracing() -> None:
    """Idempotent: no-op unless an export endpoint is configured."""
    global _configured
    if _configured:
        return
    _configured = True

    settings = get_settings()
    if not settings.otel_exporter_endpoint:
        logger.info("tracing_disabled", reason="no exporter endpoint")
        return

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create(
        {
            "service.name": settings.otel_service_name,
            "service.version": "0.1.0",
            "deployment.environment": settings.env,
        }
    )
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    logger.info("tracing_enabled", endpoint=settings.otel_exporter_endpoint)


def get_tracer(name: str = "synapse-saas") -> Any:
    """Tracer handle; safe before configure_tracing (no-op provider)."""
    from opentelemetry import trace

    return trace.get_tracer(name)


def current_trace_id() -> str | None:
    """Hex trace id of the active span, or None when not sampling."""
    from opentelemetry import trace

    ctx = trace.get_current_span().get_span_context()
    if ctx is None or not ctx.is_valid:
        return None
    return f"{ctx.trace_id:032x}"
