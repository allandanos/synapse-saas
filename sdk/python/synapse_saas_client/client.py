"""The client: one httpx transport, typed resource namespaces."""

from __future__ import annotations

from dataclasses import dataclass
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
        self.roles = RolesResource(self)
        self.billing = BillingResource(self)
        self.invoices = InvoicesResource(self)
        self.webhooks = WebhooksResource(self)
        self.files = FilesResource(self)
        self.feature_flags = FeatureFlagsResource(self)
        self.agents = AgentsResource(self)
        self.audit = AuditResource(self)
        self.admin = AdminResource(self)

    def meta(self) -> Any:
        """Framework version, active billing/identity providers, tenant isolation mode."""
        return self.request("GET", "/v1/meta") if not self._async else self.request_async("GET", "/v1/meta")

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

    def request_page(self, method: str, path: str, **kwargs: Any) -> Page:
        response = self._http.request(method, path, **kwargs)
        return _page(response)

    async def request_page_async(self, method: str, path: str, **kwargs: Any) -> Page:
        response = await self._http.request(method, path, **kwargs)
        return _page(response)

    def request_bytes(self, method: str, path: str, **kwargs: Any) -> bytes:
        response = self._http.request(method, path, **kwargs)
        return _handle_bytes(response)

    async def request_bytes_async(self, method: str, path: str, **kwargs: Any) -> bytes:
        response = await self._http.request(method, path, **kwargs)
        return _handle_bytes(response)


@dataclass(frozen=True, slots=True)
class Page:
    """One page of a list route: the items plus the server's total (`X-Total-Count`)."""

    items: list[Any]
    total: int
    limit: int
    offset: int


def _handle(response: httpx.Response) -> Any:
    if response.status_code == 204:
        return None
    body = response.json()
    if response.is_success:
        return body
    raise error_for(response.status_code, body)


def _page(response: httpx.Response) -> Page:
    items = _handle(response)
    params = dict(response.request.url.params)
    return Page(
        items=list(items or []),
        total=int(response.headers.get("X-Total-Count", len(items or []))),
        limit=int(params.get("limit", 50)),
        offset=int(params.get("offset", 0)),
    )


def _handle_bytes(response: httpx.Response) -> bytes:
    if response.is_success:
        return response.content
    raise error_for(response.status_code, response.json())


def _paging(limit: int | None, offset: int | None, **extra: Any) -> dict[str, Any]:
    params: dict[str, Any] = {k: v for k, v in extra.items() if v is not None}
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    return params


class _Resource:
    def __init__(self, client: SynapseClient) -> None:
        self._client = client

    def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        if self._client._async:
            return self._client.request_async(method, path, **kwargs)
        return self._client.request(method, path, **kwargs)

    def _page(self, method: str, path: str, **kwargs: Any) -> Any:
        if self._client._async:
            return self._client.request_page_async(method, path, **kwargs)
        return self._client.request_page(method, path, **kwargs)

    def _bytes(self, method: str, path: str, **kwargs: Any) -> Any:
        if self._client._async:
            return self._client.request_bytes_async(method, path, **kwargs)
        return self._client.request_bytes(method, path, **kwargs)


class AuthResource(_Resource):
    def me(self) -> dict:
        return self._call("GET", "/v1/auth/me")

    def register(self, email: str, password: str, display_name: str) -> dict:
        return self._call(
            "POST", "/v1/auth/register", json={"email": email, "password": password, "display_name": display_name}
        )

    def login(self, email: str, password: str) -> dict:
        """`{user, tokens}`; SSO-only accounts answer 401 with `sso_url`."""
        return self._call("POST", "/v1/auth/login", json={"email": email, "password": password})

    def refresh(self, refresh_token: str) -> dict:
        return self._call("POST", "/v1/auth/refresh", json={"refresh_token": refresh_token})

    def logout(self) -> None:
        self._call("POST", "/v1/auth/logout")

    def forgot_password(self, email: str) -> None:
        self._call("POST", "/v1/auth/forgot-password", json={"email": email})

    def reset_password(self, token: str, password: str) -> dict:
        return self._call("POST", "/v1/auth/reset-password", json={"token": token, "password": password})

    def accept_invite(self, token: str) -> dict:
        return self._call("POST", "/v1/auth/accept-invite", json={"token": token})

    def switch_org(self, organization_id: str) -> dict:
        return self._call("POST", "/v1/auth/switch-org", json={"organization_id": organization_id})


class OrgsResource(_Resource):
    def list(self) -> dict:
        return self._call("GET", "/v1/orgs")

    def create(self, name: str, slug: str | None = None) -> dict:
        return self._call("POST", "/v1/orgs", json={"name": name, "slug": slug})

    def current(self) -> dict:
        return self._call("GET", "/v1/orgs/current")

    def update(self, *, name: str | None = None, settings: dict[str, Any] | None = None) -> dict:
        payload: dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if settings is not None:
            payload["settings"] = settings
        return self._call("PATCH", "/v1/orgs/current", json=payload)


class MembersResource(_Resource):
    def list(self) -> dict:
        return self._call("GET", "/v1/orgs/current/members")

    def update(self, membership_id: str, *, role_keys: list[str] | None = None, status: str | None = None) -> dict:
        payload: dict[str, Any] = {}
        if role_keys is not None:
            payload["role_keys"] = role_keys
        if status is not None:
            payload["status"] = status
        return self._call("PATCH", f"/v1/memberships/{membership_id}", json=payload)

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

    def resume(self) -> dict:
        return self._call("POST", "/v1/subscription/resume")

    def plans_page(self, *, limit: int | None = None, offset: int | None = None) -> Page:
        return self._page("GET", "/v1/plans", params=_paging(limit, offset))


class UsageResource(_Resource):
    def summary(self, period: str | None = None) -> dict:
        params = {"period": period} if period else None
        return self._call("GET", "/v1/usage/summary", params=params)

    def check(self, metric: str, quantity: int = 1) -> dict:
        return self._call("GET", "/v1/usage/check", params={"metric": metric, "quantity": quantity})

    def consume(self, metric: str, quantity: int = 1, *, idempotency_key: str | None = None) -> dict:
        event: dict[str, Any] = {"metric": metric, "quantity": quantity}
        if idempotency_key is not None:
            event["idempotency_key"] = idempotency_key
        return self._call("POST", "/v1/usage/consume", json={"events": [event]})

    def consume_batch(self, events: list[dict[str, Any]]) -> list[dict]:
        """All-or-nothing: the first breach raises SynapseLimitError and nothing is counted."""
        return self._call("POST", "/v1/usage/consume-batch", json={"events": events})

    def record(self, events: list[dict[str, Any]]) -> list[dict]:
        """Meter without enforcing (never blocks). `idempotency_key` per event dedupes retries."""
        return self._call("POST", "/v1/usage/events", json={"events": events})

    def set_gauge(self, metric: str, value: int) -> dict:
        """Gauges are levels (seats, projects, bytes): set the absolute value."""
        return self._call("POST", "/v1/usage/gauge", json={"metric": metric, "value": value})

    def adjust_gauge(self, metric: str, delta: int) -> dict:
        """Move a gauge by `delta` (never below zero)."""
        return self._call("POST", "/v1/usage/gauge", json={"metric": metric, "delta": delta})


class EntitlementsResource(_Resource):
    def effective(self) -> dict:
        return self._call("GET", "/v1/entitlements")

    def grant(
        self,
        organization_id: str,
        feature_key: str,
        source: str,
        *,
        duration_days: int | None = None,
        limit_value: int | None = None,
    ) -> dict:
        """Platform-operator action: requires a platform-admin bearer, targets any org."""
        payload: dict[str, Any] = {"feature_key": feature_key, "source": source}
        if duration_days is not None:
            payload["duration_days"] = duration_days
        if limit_value is not None:
            payload["limit_value"] = limit_value
        return self._call("POST", f"/v1/admin/orgs/{organization_id}/entitlements/grants", json=payload)


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


class RolesResource(_Resource):
    def list(self) -> list:
        return self._call("GET", "/v1/roles")

    def permissions(self) -> list:
        """The permission catalog (`resource:action` keys)."""
        return self._call("GET", "/v1/permissions")

    def create(self, key: str, name: str, permissions: list[str], *, description: str | None = None) -> dict:
        payload: dict[str, Any] = {"key": key, "name": name, "permissions": permissions}
        if description is not None:
            payload["description"] = description
        return self._call("POST", "/v1/roles", json=payload)

    def update(
        self,
        role_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        permissions: list[str] | None = None,
    ) -> dict:
        payload = {k: v for k, v in {"name": name, "description": description, "permissions": permissions}.items() if v is not None}
        return self._call("PATCH", f"/v1/roles/{role_id}", json=payload)

    def delete(self, role_id: str) -> None:
        self._call("DELETE", f"/v1/roles/{role_id}")


class BillingResource(_Resource):
    def checkout(self, plan_key: str) -> dict:
        """`{url}` for hosted providers, or manual payment instructions."""
        return self._call("POST", "/v1/billing/checkout", json={"plan_key": plan_key})

    def confirm_checkout(self, plan_key: str) -> dict:
        """Manual provider only (409 `checkout_confirm_not_allowed` elsewhere)."""
        return self._call("POST", "/v1/billing/checkout/confirm", json={"plan_key": plan_key})

    def portal_url(self) -> dict:
        return self._call("GET", "/v1/billing/portal-url")

    def spend_summary(self) -> dict:
        return self._call("GET", "/v1/billing/spend-summary")

    def spend_monthly(self) -> list:
        return self._call("GET", "/v1/billing/spend-monthly")


class InvoicesResource(_Resource):
    def list(self, *, limit: int | None = None, offset: int | None = None) -> list:
        return self._call("GET", "/v1/billing/invoices", params=_paging(limit, offset))

    def list_page(self, *, limit: int | None = None, offset: int | None = None) -> Page:
        return self._page("GET", "/v1/billing/invoices", params=_paging(limit, offset))

    def get(self, invoice_id: str) -> dict:
        return self._call("GET", f"/v1/billing/invoices/{invoice_id}")

    def pdf(self, invoice_id: str) -> bytes:
        return self._bytes("GET", f"/v1/billing/invoices/{invoice_id}/pdf")

    def draft(self, *, period: str | None = None) -> dict:
        """Draft (or return) the period invoice: plan + overage + prorated adjustments."""
        return self._call("POST", "/v1/billing/invoices/draft", json={"period": period} if period else {})

    def finalize(self, invoice_id: str) -> dict:
        return self._call("POST", f"/v1/billing/invoices/{invoice_id}/finalize")


class WebhooksResource(_Resource):
    def list_endpoints(self, *, limit: int | None = None, offset: int | None = None) -> list:
        return self._call("GET", "/v1/webhooks/endpoints", params=_paging(limit, offset))

    def create_endpoint(self, url: str, *, events: list[str] | None = None, description: str | None = None) -> dict:
        """The signing `secret` is returned exactly once."""
        payload: dict[str, Any] = {"url": url, "events": events or []}
        if description is not None:
            payload["description"] = description
        return self._call("POST", "/v1/webhooks/endpoints", json=payload)

    def delete_endpoint(self, endpoint_id: str) -> None:
        self._call("DELETE", f"/v1/webhooks/endpoints/{endpoint_id}")

    def list_deliveries(
        self, *, endpoint_id: str | None = None, limit: int | None = None, offset: int | None = None
    ) -> list:
        return self._call("GET", "/v1/webhooks/deliveries", params=_paging(limit, offset, endpoint_id=endpoint_id))

    def retry_delivery(self, delivery_id: str) -> dict:
        return self._call("POST", f"/v1/webhooks/deliveries/{delivery_id}/retry")


class FilesResource(_Resource):
    def list(self, *, limit: int | None = None, offset: int | None = None) -> list:
        return self._call("GET", "/v1/files", params=_paging(limit, offset))

    def list_page(self, *, limit: int | None = None, offset: int | None = None) -> Page:
        return self._page("GET", "/v1/files", params=_paging(limit, offset))

    def upload(self, name: str, content: bytes, content_type: str = "application/octet-stream") -> dict:
        """Direct multipart upload (≤10 MiB). Larger objects: `presign_upload` + `complete`."""
        return self._call("POST", "/v1/files", files={"file": (name, content, content_type)})

    def download(self, file_id: str) -> bytes:
        return self._bytes("GET", f"/v1/files/{file_id}")

    def presign_download(self, file_id: str) -> dict:
        return self._call("POST", f"/v1/files/{file_id}/presign")

    def presign_upload(self, name: str, size_bytes: int, content_type: str = "application/octet-stream") -> dict:
        """`{id, url, method, headers, expires_in}` — PUT the bytes there, then `complete(id)`."""
        return self._call(
            "POST",
            "/v1/files/presign-upload",
            json={"name": name, "size_bytes": size_bytes, "content_type": content_type},
        )

    def complete(self, file_id: str) -> dict:
        return self._call("POST", f"/v1/files/{file_id}/complete")

    def delete(self, file_id: str) -> None:
        self._call("DELETE", f"/v1/files/{file_id}")


class FeatureFlagsResource(_Resource):
    def check(self, key: str) -> dict:
        """`{key, enabled}` for the caller's org + user (overrides + rollout aware)."""
        return self._call("GET", f"/v1/feature-flags/check/{key}")

    # Platform-admin surface
    def list(self, *, limit: int | None = None, offset: int | None = None) -> list:
        return self._call("GET", "/v1/feature-flags", params=_paging(limit, offset))

    def create(
        self,
        key: str,
        name: str,
        *,
        description: str | None = None,
        enabled: bool = False,
        rollout_percentage: int | None = None,
    ) -> dict:
        payload: dict[str, Any] = {"key": key, "name": name, "enabled": enabled}
        if description is not None:
            payload["description"] = description
        if rollout_percentage is not None:
            payload["rollout_percentage"] = rollout_percentage
        return self._call("POST", "/v1/feature-flags", json=payload)

    def update(self, key: str, *, enabled: bool | None = None, rollout_percentage: int | None = None) -> dict:
        payload = {k: v for k, v in {"enabled": enabled, "rollout_percentage": rollout_percentage}.items() if v is not None}
        return self._call("PATCH", f"/v1/feature-flags/{key}", json=payload)

    def list_overrides(self, key: str) -> list:
        return self._call("GET", f"/v1/feature-flags/{key}/overrides")

    def set_override(
        self,
        key: str,
        *,
        enabled: bool,
        organization_id: str | None = None,
        user_id: str | None = None,
        note: str | None = None,
    ) -> dict:
        payload: dict[str, Any] = {"enabled": enabled}
        for k, v in {"organization_id": organization_id, "user_id": user_id, "note": note}.items():
            if v is not None:
                payload[k] = v
        return self._call("POST", f"/v1/feature-flags/{key}/overrides", json=payload)

    def delete_override(self, override_id: str) -> None:
        self._call("DELETE", f"/v1/feature-flags/overrides/{override_id}")


class AgentsResource(_Resource):
    """Registry + governance (ADR 0007); every call is behind the `agents` feature."""

    def list(self, *, limit: int | None = None, offset: int | None = None) -> list:
        return self._call("GET", "/v1/agents", params=_paging(limit, offset))

    def create(self, slug: str, name: str, *, description: str | None = None, config: dict[str, Any] | None = None) -> dict:
        payload: dict[str, Any] = {"slug": slug, "name": name, "config": config or {}}
        if description is not None:
            payload["description"] = description
        return self._call("POST", "/v1/agents", json=payload)

    def get(self, agent_id: str) -> dict:
        return self._call("GET", f"/v1/agents/{agent_id}")

    def update(
        self,
        agent_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> dict:
        payload = {k: v for k, v in {"name": name, "description": description, "config": config}.items() if v is not None}
        return self._call("PATCH", f"/v1/agents/{agent_id}", json=payload)

    def delete(self, agent_id: str) -> None:
        self._call("DELETE", f"/v1/agents/{agent_id}")

    def enable(self, agent_id: str) -> dict:
        return self._call("POST", f"/v1/agents/{agent_id}/enable")

    def disable(self, agent_id: str) -> dict:
        return self._call("POST", f"/v1/agents/{agent_id}/disable")


class AuditResource(_Resource):
    def list(self, *, limit: int | None = None, offset: int | None = None, **filters: Any) -> Any:
        return self._call("GET", "/v1/audit", params=_paging(limit, offset, **filters))


class AdminResource(_Resource):
    """Platform-operator surface (platform-admin bearer, explicit org ids) — ADR 0008."""

    def entitlements(self, organization_id: str) -> dict:
        return self._call("GET", f"/v1/admin/orgs/{organization_id}/entitlements")

    def grant(self, organization_id: str, body: dict[str, Any]) -> dict:
        return self._call("POST", f"/v1/admin/orgs/{organization_id}/entitlements/grants", json=body)

    def revoke_grant(self, organization_id: str, grant_id: str) -> None:
        self._call("DELETE", f"/v1/admin/orgs/{organization_id}/entitlements/grants/{grant_id}")

    def pay_invoice(self, invoice_id: str, amount_cents: int, *, reference: str | None = None) -> dict:
        payload: dict[str, Any] = {"amount_cents": amount_cents}
        if reference is not None:
            payload["reference"] = reference
        return self._call("POST", f"/v1/billing/admin/invoices/{invoice_id}/pay", json=payload)

    def void_invoice(self, invoice_id: str) -> dict:
        return self._call("POST", f"/v1/billing/admin/invoices/{invoice_id}/void")

    def revenue_summary(self) -> dict:
        return self._call("GET", "/v1/billing/admin/revenue-summary")

    def revenue_monthly(self) -> list:
        return self._call("GET", "/v1/billing/admin/revenue-monthly")

    def suspend_org(self, organization_id: str) -> None:
        self._call("POST", f"/v1/orgs/{organization_id}/suspend")

    def unsuspend_org(self, organization_id: str) -> None:
        self._call("DELETE", f"/v1/orgs/{organization_id}/suspend")
