"""Tracing unit tests — inert by default, spans when configured via test provider."""

from __future__ import annotations

import pytest

from synapse_saas.core.tracing import configure_tracing, current_trace_id, get_tracer

pytestmark = []


class TestInertDefault:
    def test_configure_without_endpoint_is_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from synapse_saas.core import tracing as tracing_module
        from synapse_saas.core.config import get_settings

        monkeypatch.setenv("SYNAPSE_OTEL_EXPORTER_ENDPOINT", "")
        get_settings.cache_clear()
        tracing_module._configured = False
        configure_tracing()  # must not raise; no exporter configured
        get_settings.cache_clear()

    async def test_no_trace_id_outside_span(self) -> None:
        # With the default no-op provider there is no valid span context
        assert current_trace_id() is None

    async def test_span_with_real_provider_records(self) -> None:
        """Attach an in-memory SDK provider: spans record, trace ids resolve,
        nested spans share a trace — the contract exporters rely on."""
        from opentelemetry.sdk.trace import TracerProvider

        import synapse_saas.core.tracing as tracing_module

        tracer_module_provider = TracerProvider()
        from opentelemetry import trace

        trace.set_tracer_provider(tracer_module_provider)
        try:
            tracer = get_tracer("test")
            with tracer.start_as_current_span("test-span") as span:
                assert span.is_recording()
                trace_id = current_trace_id()
                assert trace_id is not None and len(trace_id) == 32
        finally:
            # restore inert default for other tests
            trace.set_tracer_provider(trace.NoOpTracerProvider())
            tracing_module._configured = False

    async def test_nested_spans_share_trace(self) -> None:
        tracer = get_tracer("test")
        with tracer.start_as_current_span("outer"):
            outer = current_trace_id()
            with tracer.start_as_current_span("inner"):
                inner = current_trace_id()
            assert outer == inner


class TestProblemDocs:
    async def test_problem_carries_request_or_trace_id(self) -> None:
        from synapse_saas.core.errors import AuthenticationError

        doc = AuthenticationError("nope").to_problem(request_id="req_abc")
        assert doc["request_id"] == "req_abc"
