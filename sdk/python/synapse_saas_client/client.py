"""The client: one httpx transport, typed resource namespaces."""

from __future__ import annotations

from typing import Any

import httpx

from synapse_saas_client.errors import error_for


class SynapseClient:
    """Sync client over the /v1 API.

    Use `api_key=` for programmatic access (org pinned server-side — no
    org header needed) or `access_token=` for a user session. For async,
    construct with `is_async=True` and every method is a coroutine.
    """

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        access_token: str | None = None,
        org_id: str | None = None,
        timeout: float = 30.0,
        is_async: bool = False,
        _transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key and not access_token:
            msg = "api_key or access_token is required"
            raise ValueError(msg)
        headers: dict[str, str] = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        elif access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        if org_id:
            headers["X-Org-Id"] = org_id

        self._base = base_url.rstrip("/")
        self._async = is_async
        client_kwargs: dict[str, Any] = {
            "base_url": self._base,
            "headers": headers,
            "timeout": timeout,
        }
        if _transport is not None:
            client_kwargs["transport"] = _transport
        self._http = (
            httpx.AsyncClient(**client_kwargs)
            if is_async
            else httpx.Client(**client_kwargs)
        )

        # Resource namespaces
        self.auth = AuthResource(self)
        self.orgs = OrgsResource(self)
        self.members = MembersResource(self)
        self.subscription = SubscriptionResource(self)
        self.usage = UsageResource(self)
        self.entitlements = EntitlementsResource(self)
        self.api_keys = ApiKeysResource(self)

    def close(self) -> None:
        if self._async:
            raise RuntimeError("use 'await client.aclose()' on async clients")

    async def aclose(self) -> None:
        if self._async:
            await self._http.aclose()

    def __enter__(self) -> SynapseClient:
        return self

    def __exit__(self, *exc: object) -> None:
        if not self._async:
            self._http.close()

    # ── Request core ────────────────────────────────────────────────────────────

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._http.request(method, path, **kwargs)
        return _handle(response)

    async def request_async(self, method: str, path: str, **kwargs: Any) -> Any:
        response = await self._http.request(method, path, **kwargs)
        return _handle(response)


def _handle(response: httpx.Response) -> Any:
    if response.status_code == 204:
        return None
    body = response.json()
    if response.is_success:
        return body
    raise error_for(response.status_code, body)


class _Resource:
    def __init__(self, client: SynapseClient) -> None:
        self._client = client

    def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        if self._client._async:
            return self._client.request_async(method, path, **kwargs)
        return self._client.request(method, path, **kwargs)


class AuthResource(_Resource):
    def me(self) -> dict:
        return self._call("GET", "/v1/auth/me")

    def switch_org(self, organization_id: str) -> dict:
        return self._call("POST", "/v1/auth/switch-org", json={"organization_id": organization_id})


class OrgsResource(_Resource):
    def list(self) -> dict:
        return self._call("GET", "/v1/orgs")

    def create(self, name: str, slug: str | None = None) -> dict:
        return self._call("POST", "/v1/orgs", json={"name": name, "slug": slug})

    def current(self) -> dict:
        return self._call("GET", "/v1/orgs/current")


class MembersResource(_Resource):
    def list(self) -> dict:
        return self._call("GET", "/v1/orgs/current/members")

    def invite(self, email: str, role_keys: list[str] | None = None) -> dict:
        return self._call(
            "POST",
            "/v1/orgs/current/members/invite",
            json={"email": email, "role_keys": role_keys or ["member"]},
        )

    def remove(self, membership_id: str) -> None:
        self._call("DELETE", f"/v1/memberships/{membership_id}")


class SubscriptionResource(_Resource):
    def current(self) -> dict:
        """Subscription + entitlements + usage snapshot in one call."""
        return self._call("GET", "/v1/subscription")

    def plans(self) -> list:
        return self._call("GET", "/v1/plans")

    def change(self, plan_key: str) -> dict:
        return self._call("POST", "/v1/subscription/change", json={"plan_key": plan_key})

    def start_trial(self, plan_key: str) -> dict:
        return self._call("POST", "/v1/subscription/trial", json={"plan_key": plan_key})

    def cancel(self, at_period_end: bool = True) -> dict:
        return self._call("POST", "/v1/subscription/cancel", json={"at_period_end": at_period_end})


class UsageResource(_Resource):
    def summary(self, period: str | None = None) -> dict:
        params = {"period": period} if period else None
        return self._call("GET", "/v1/usage/summary", params=params)

    def check(self, metric: str, quantity: int = 1) -> dict:
        return self._call("GET", "/v1/usage/check", params={"metric": metric, "quantity": quantity})

    def consume(self, metric: str, quantity: int = 1) -> dict:
        return self._call(
            "POST", "/v1/usage/consume", json={"events": [{"metric": metric, "quantity": quantity}]}
        )


class EntitlementsResource(_Resource):
    def effective(self) -> dict:
        return self._call("GET", "/v1/entitlements")

    def grant(
        self,
        feature_key: str,
        source: str,
        *,
        duration_days: int | None = None,
        limit_value: int | None = None,
    ) -> dict:
        payload: dict[str, Any] = {"feature_key": feature_key, "source": source}
        if duration_days is not None:
            payload["duration_days"] = duration_days
        if limit_value is not None:
            payload["limit_value"] = limit_value
        return self._call("POST", "/v1/entitlements/grants", json=payload)


class ApiKeysResource(_Resource):
    def list(self) -> list:
        return self._call("GET", "/v1/api-keys")

    def create(self, name: str, scopes: list[str] | None = None, expires_in_days: int | None = None) -> dict:
        """Returns the plaintext key exactly once — persist it immediately."""
        payload: dict[str, Any] = {"name": name, "scopes": scopes or []}
        if expires_in_days is not None:
            payload["expires_in_days"] = expires_in_days
        return self._call("POST", "/v1/api-keys", json=payload)

    def revoke(self, key_id: str) -> None:
        self._call("DELETE", f"/v1/api-keys/{key_id}")
