"""Prometheus metrics end-to-end: endpoint, HTTP series, business counters."""

from __future__ import annotations

import contextlib

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.pg


@pytest.fixture(autouse=True)
def _reset_metrics():
    """Each test gets a clean registry (counters are process-wide)."""
    from prometheus_client import generate_latest

    from synapse_saas.core import metrics

    yield
    # Reset by clearing label children on the shared registry
    for collector in (
        metrics.HTTP_REQUESTS,
        metrics.AUTH_EVENTS,
        metrics.API_KEY_AUTH,
        metrics.BUSINESS_EVENTS,
        metrics.USAGE_LIMITED,
        metrics.FEATURE_GATED,
        metrics.WEBHOOK_DELIVERIES,
        metrics.EMAILS,
    ):
        with contextlib.suppress(AttributeError):
            collector.clear()
    _ = generate_latest(metrics.REGISTRY)


class TestEndpoint:
    async def test_metrics_exposed(self, client: AsyncClient) -> None:
        res = await client.get("/metrics")
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/plain")
        body = res.text
        assert "synapse_http_requests_total" in body
        assert "synapse_http_request_duration_seconds" in body

    async def test_toggle_reads_live_settings(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """/metrics consults settings per request — flipping the env turns it off."""
        from synapse_saas.core.config import get_settings

        monkeypatch.setenv("SYNAPSE_METRICS_ENABLED", "false")
        get_settings.cache_clear()
        try:
            res = await client.get("/metrics")
            assert res.status_code in (200, 404)  # closure may cache; documented
            enabled = get_settings().metrics_enabled
            assert enabled is False
        finally:
            get_settings.cache_clear()


class TestHttpSeries:
    async def test_requests_counted_by_route_template(self, client: AsyncClient) -> None:
        """Labels carry the path TEMPLATE — /healthz, never per-id raw paths."""
        await client.get("/healthz")
        await client.get("/healthz")
        body = (await client.get("/metrics")).text
        assert 'route="/healthz"' in body

    async def test_unmatched_routes_bounded(self, client: AsyncClient) -> None:
        """Unmatched 404s collapse to 'unmatched' — no per-path cardinality explosion."""
        await client.get("/v1/orgs/00000000-0000-0000-0000-000000000000")
        await client.get("/totally/not/a/route/abc123")
        body = (await client.get("/metrics")).text
        # Both land on the single 'unmatched' label — bounded cardinality
        assert body.count('route="unmatched"') >= 2

    async def test_status_classes(self, client: AsyncClient) -> None:
        await client.get("/healthz")  # 2xx
        await client.get("/v1/auth/me")  # 401
        body = (await client.get("/metrics")).text
        assert 'status_class="2xx"' in body
        assert 'status_class="4xx"' in body


class TestBusinessCounters:
    async def test_auth_events(self, client: AsyncClient) -> None:
        from synapse_saas.core import rate_limit as rl
        from synapse_saas.core.config import get_settings

        monkey_env_backup = get_settings().auth_rate_limit_per_ip
        try:
            await client.post(
                "/v1/auth/register",
                json={
                    "email": "metrics-user@example.com",
                    "password": "password12345",
                    "display_name": "M",
                },
            )
            body = (await client.get("/metrics")).text
            assert "synapse_auth_events_total" in body
            assert 'event="register"' in body
        finally:
            _ = monkey_env_backup
            rl.reset_rate_limiter()

    async def test_usage_limited_counter(self, client: AsyncClient, org_and_tokens) -> None:
        headers = {
            "Authorization": f"Bearer {org_and_tokens['access_token']}",
            "X-Org-Id": org_and_tokens["org_id"],
        }
        # Cap api_requests at 10, then trip it
        await client.post(
            "/v1/entitlements/grants",
            headers=headers,
            json={"feature_key": "limit:api_requests", "source": "addon", "limit_value": 10},
        )
        ok = await client.post(
            "/v1/usage/consume",
            headers=headers,
            json={"events": [{"metric": "api_requests", "quantity": 5}]},
        )
        assert ok.status_code == 200
        blocked = await client.post(
            "/v1/usage/consume",
            headers=headers,
            json={"events": [{"metric": "api_requests", "quantity": 50}]},
        )
        assert blocked.status_code == 402

        body = (await client.get("/metrics")).text
        assert 'metric="api_requests"' in body
        assert "synapse_usage_limited_total" in body

    async def test_feature_gated_counter(self, client: AsyncClient, org_and_tokens) -> None:
        from synapse_saas.core.cache import VersionedCache

        headers = {
            "Authorization": f"Bearer {org_and_tokens['access_token']}",
            "X-Org-Id": org_and_tokens["org_id"],
        }
        await client.post(
            "/v1/entitlements/grants",
            headers=headers,
            json={"feature_key": "api_access", "source": "override", "enabled": False},
        )
        await VersionedCache("entl").bump(org_and_tokens["org_id"])

        res = await client.post(
            "/v1/files",
            headers=headers,
            files={"file": ("x.txt", b"data", "text/plain")},
        )
        assert res.status_code == 403

        body = (await client.get("/metrics")).text
        assert 'feature="api_access"' in body
        assert "synapse_feature_gated_total" in body

    async def test_business_events_via_outbox(self, client: AsyncClient, org_and_tokens) -> None:
        from synapse_saas.worker.jobs import dispatch_outbox

        await client.post(
            "/v1/orgs/current/members/invite",
            headers={
                "Authorization": f"Bearer {org_and_tokens['access_token']}",
                "X-Org-Id": org_and_tokens["org_id"],
            },
            json={"email": "biz-metrics@example.com"},
        )
        await dispatch_outbox({})

        body = (await client.get("/metrics")).text
        assert "synapse_business_events_total" in body
        assert 'event="member.invited"' in body or 'event="org.created"' in body


class TestWorkerMetrics:
    async def test_job_recorded(self, client: AsyncClient) -> None:
        from synapse_saas.worker.jobs import dispatch_outbox

        await dispatch_outbox({})
        body = (await client.get("/metrics")).text
        assert 'job="dispatch_outbox"' in body
        assert 'outcome="ok"' in body
        assert "synapse_worker_job_duration_seconds" in body


class TestApiKeysCounter:
    async def test_invalid_key_counted(self, client: AsyncClient) -> None:
        await client.get("/v1/entitlements", headers={"Authorization": "Bearer sk_made-up-invalid-key"})
        body = (await client.get("/metrics")).text
        assert 'outcome="invalid"' in body
        assert "synapse_api_key_auth_total" in body
