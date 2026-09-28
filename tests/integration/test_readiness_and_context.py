"""WS-E: readiness that fails loudly, and request correlation that actually reaches logs and problem docs."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from synapse_saas.identity.dependencies import CurrentUser
from synapse_saas.tenancy.dependencies import TenantDep

pytestmark = pytest.mark.pg


class TestReadiness:
    async def test_readyz_ok(self, client: AsyncClient) -> None:
        res = await client.get("/readyz")
        assert res.status_code == 200
        assert res.json()["checks"]["database"] == "ok"

    async def test_readyz_503_when_db_down(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A dead database must fail the probe — a 200 with `error` inside is invisible to Kubernetes."""
        import synapse_saas.api.app as app_module

        class _DeadSession:
            async def __aenter__(self) -> _DeadSession:
                return self

            async def __aexit__(self, *exc: object) -> None:
                pass

            async def execute(self, *a: Any, **k: Any) -> None:
                raise ConnectionError("connection refused")

        monkeypatch.setattr(app_module, "get_session_factory", lambda: _DeadSession)
        res = await client.get("/readyz")
        assert res.status_code == 503, res.text
        body = res.json()
        assert body["status"] == "error" and body["checks"]["database"].startswith("error")


class TestRequestCorrelation:
    async def test_problem_doc_carries_the_server_request_id(self, client: AsyncClient) -> None:
        res = await client.get("/v1/orgs/current")  # no auth ⇒ 401 problem document
        assert res.status_code == 401
        server_id = res.headers["X-Request-Id"]
        assert server_id.startswith("req_")
        assert res.json()["request_id"] == server_id

    async def test_client_request_id_is_honoured(self, client: AsyncClient) -> None:
        res = await client.get("/v1/orgs/current", headers={"X-Request-Id": "client-abc"})
        assert res.headers["X-Request-Id"] == "client-abc"
        assert res.json()["request_id"] == "client-abc"

    async def test_logs_carry_request_org_and_user_ids(
        self, client: AsyncClient, app, org_and_tokens
    ) -> None:
        """Inside a tenant-scoped handler the structlog context names request, org and user."""
        import structlog

        captured: dict[str, Any] = {}

        async def probe(tenant: TenantDep, user: CurrentUser) -> dict[str, Any]:
            captured.update(structlog.contextvars.get_contextvars())
            return {"ok": True}

        app.add_api_route("/__probe/context", probe, methods=["GET"])

        res = await client.get(
            "/__probe/context",
            headers={
                "Authorization": f"Bearer {org_and_tokens['access_token']}",
                "X-Org-Id": org_and_tokens["org_id"],
                "X-Request-Id": "req-probe-1",
            },
        )
        assert res.status_code == 200, res.text
        assert captured["request_id"] == "req-probe-1"
        assert captured["org_id"] == org_and_tokens["org_id"]
        assert "user_id" in captured
        # …and nothing leaks into the next request on this task
        assert "request_id" not in structlog.contextvars.get_contextvars()

    async def test_request_span_is_current(
        self, client: AsyncClient, app, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Handlers run INSIDE the request span: trace ids reach logs and problem docs."""
        pytest.importorskip("opentelemetry.sdk")
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        # The global provider can only be set once per process; go through the module's tracer factory instead
        from synapse_saas.core import tracing

        monkeypatch.setattr(tracing, "get_tracer", lambda name="synapse-saas": provider.get_tracer(name))

        seen: dict[str, Any] = {}

        async def probe() -> dict[str, Any]:
            ctx = trace.get_current_span().get_span_context()
            seen["valid"] = ctx.is_valid
            seen["trace_id"] = f"{ctx.trace_id:032x}" if ctx.is_valid else None
            return {"ok": True}

        app.add_api_route("/__probe/span", probe, methods=["GET"])
        res = await client.get("/__probe/span")
        assert res.status_code == 200
        assert seen["valid"] is True, "the handler must run inside the request span"
        spans = exporter.get_finished_spans()
        assert any(s.name == "GET /__probe/span" for s in spans)
        assert (
            seen["trace_id"]
            == f"{next(s for s in spans if s.name == 'GET /__probe/span').context.trace_id:032x}"
        )
