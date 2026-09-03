"""SDK unit tests — request shaping and error mapping against a fake transport."""

from __future__ import annotations

import json

import httpx
import pytest

from synapse_saas_client import (
    SynapseAuthError,
    SynapseClient,
    SynapseFeatureGatedError,
    SynapseLimitError,
    SynapseNotFoundError,
)


class FakeTransport(httpx.BaseTransport):
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        method = request.method

        if path == "/v1/auth/me" and method == "GET":
            return httpx.Response(200, json={"id": "u1", "orgs": []})
        if path == "/v1/usage/consume" and method == "POST":
            body = json.loads(request.content)
            if body["events"][0]["quantity"] > 100:
                return httpx.Response(
                    402,
                    json={"type": "…/usage_limit_exceeded", "title": "usage limit exceeded", "metric": "api_requests", "limit": 100},
                )
            return httpx.Response(200, json={"metric": "api_requests", "total": body["events"][0]["quantity"]})
        if path == "/v1/billing/checkout" and method == "POST":
            return httpx.Response(
                403,
                json={"type": "…/feature_not_entitled", "feature": "advanced_reports", "available_in": ["pro"], "upgrade_url": "/dashboard/billing"},
            )
        if path.startswith("/v1/api-keys/") and method == "DELETE":
            return httpx.Response(204)
        if path == "/v1/orgs/00000000-0000-0000-0000-000000000000/entitlements" and method == "GET":
            return httpx.Response(404, json={"title": "not found"})
        if path == "/v1/nope" and method == "GET":
            return httpx.Response(401, json={"title": "unauthorized"})
        return httpx.Response(200, json={})


@pytest.fixture
def transport() -> FakeTransport:
    return FakeTransport()


@pytest.fixture
def client(transport: FakeTransport) -> SynapseClient:
    return SynapseClient(
        "http://test",
        api_key="sk_test",
        org_id="11111111-1111-1111-1111-111111111111",
        timeout=5.0,
        _transport=transport,  # type: ignore[call-arg]
    )


class TestRequests:
    def test_auth_header_and_org_header(self, client: SynapseClient, transport: FakeTransport) -> None:
        client.auth.me()
        request = transport.requests[-1]
        assert request.headers["Authorization"] == "Bearer sk_test"
        assert request.headers["X-Org-Id"] == "11111111-1111-1111-1111-111111111111"

    def test_consume_payload(self, client: SynapseClient, transport: FakeTransport) -> None:
        result = client.usage.consume("api_requests", 5)
        assert result["total"] == 5
        body = json.loads(transport.requests[-1].content)
        assert body == {"events": [{"metric": "api_requests", "quantity": 5}]}

    def test_delete_returns_none(self, client: SynapseClient) -> None:
        assert client.api_keys.revoke("22222222-2222-2222-2222-222222222222") is None


class TestErrors:
    def test_limit_error_typed(self, client: SynapseClient) -> None:
        with pytest.raises(SynapseLimitError) as exc_info:
            client.usage.consume("api_requests", 500)
        assert exc_info.value.metric == "api_requests"
        assert exc_info.value.limit == 100

    def test_feature_gate_typed(self, client: SynapseClient, transport: FakeTransport) -> None:
        # Map a real 403 through the SDK's own mapping helper
        from synapse_saas_client.errors import error_for

        body = {
            "type": "…/feature_not_entitled",
            "title": "feature not entitled",
            "status": 403,
            "feature": "advanced_reports",
            "available_in": ["pro"],
            "upgrade_url": "/dashboard/billing",
        }
        err = error_for(403, body)
        assert isinstance(err, SynapseFeatureGatedError)
        assert err.feature == "advanced_reports"
        assert err.available_in == ["pro"]

    def test_404_typed(self) -> None:
        from synapse_saas_client.errors import error_for

        err = error_for(404, {"title": "not found"})
        assert isinstance(err, SynapseNotFoundError)

    def test_401_typed(self) -> None:
        from synapse_saas_client.errors import error_for

        err = error_for(401, {"title": "unauthorized"})
        assert isinstance(err, SynapseAuthError)


class TestConstructor:
    def test_requires_credentials(self) -> None:
        with pytest.raises(ValueError, match="api_key or access_token"):
            SynapseClient("http://test")

    def test_access_token_mode(self, transport: FakeTransport) -> None:
        c = SynapseClient("http://test", access_token="jwt", _transport=transport)  # type: ignore[call-arg]
        c.auth.me()
        assert transport.requests[-1].headers["Authorization"] == "Bearer jwt"
