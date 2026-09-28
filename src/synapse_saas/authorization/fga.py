"""Thin OpenFGA HTTP client (no SDK) — check, write/delete tuples, list objects, models.

Every method raises `FgaError` on transport or non-2xx; callers decide the
failure mode (`AuthorizationService` fails closed in production by default).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from synapse_saas.core.config import get_settings
from synapse_saas.core.errors import DomainError
from synapse_saas.core.logging import get_logger

logger = get_logger(__name__)


class FgaError(DomainError):
    status = 503
    title = "authorization_backend_unavailable"


@dataclass(frozen=True, slots=True)
class Tuple:
    user: str  # "user:<uuid>" or "organization:<uuid>"
    relation: str
    object: str  # "organization:<uuid>" / "project:<uuid>"

    def as_key(self) -> dict[str, str]:
        return {"user": self.user, "relation": self.relation, "object": self.object}


class FgaClient:
    def __init__(
        self,
        *,
        url: str | None = None,
        store_id: str | None = None,
        model_id: str | None = None,
        api_token: str | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        settings = get_settings()
        self.url = (url or settings.openfga_url).rstrip("/")
        self.store_id = store_id or settings.openfga_store_id
        self.model_id = model_id or settings.openfga_model_id
        self._token = api_token if api_token is not None else settings.openfga_api_token
        self._http = http

    @property
    def configured(self) -> bool:
        return bool(self.url and self.store_id)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        if not self.url:
            raise FgaError("OpenFGA is not configured (SYNAPSE_OPENFGA_URL)")
        from synapse_saas.core.http import get_http_client

        client = self._http or get_http_client()
        try:
            response = await client.post(f"{self.url}{path}", json=body, headers=self._headers(), timeout=5)
        except httpx.HTTPError as exc:
            raise FgaError(f"OpenFGA unreachable: {exc}") from exc
        if response.status_code >= 300:
            raise FgaError(
                f"OpenFGA {path} answered {response.status_code}",
                extras={"body": response.text[:500]},
            )
        data: dict[str, Any] = response.json() if response.content else {}
        return data

    def _store_path(self, suffix: str) -> str:
        if not self.store_id:
            raise FgaError("OpenFGA store id is not configured (SYNAPSE_OPENFGA_STORE_ID)")
        return f"/stores/{self.store_id}{suffix}"

    # ── Checks ──────────────────────────────────────────────────────────────────

    async def check(self, user: str, relation: str, obj: str) -> bool:
        body: dict[str, Any] = {"tuple_key": {"user": user, "relation": relation, "object": obj}}
        if self.model_id:
            body["authorization_model_id"] = self.model_id
        data = await self._post(self._store_path("/check"), body)
        return bool(data.get("allowed", False))

    async def list_objects(self, user: str, relation: str, object_type: str) -> list[str]:
        body: dict[str, Any] = {"user": user, "relation": relation, "type": object_type}
        if self.model_id:
            body["authorization_model_id"] = self.model_id
        data = await self._post(self._store_path("/list-objects"), body)
        return [str(o) for o in data.get("objects", [])]

    # ── Tuples ──────────────────────────────────────────────────────────────────

    async def write(self, writes: list[Tuple] = (), deletes: list[Tuple] = ()) -> None:  # type: ignore[assignment]
        """Write and delete tuples. Duplicate writes / missing deletes are tolerated
        (one request per tuple keeps the operation idempotent under retries)."""
        for tup in writes:
            try:
                await self._post(
                    self._store_path("/write"), self._body({"writes": {"tuple_keys": [tup.as_key()]}})
                )
            except FgaError as exc:
                if "already exists" not in str(exc.extras.get("body", "")):
                    raise
        for tup in deletes:
            try:
                await self._post(
                    self._store_path("/write"), self._body({"deletes": {"tuple_keys": [tup.as_key()]}})
                )
            except FgaError as exc:
                if "not found" not in str(exc.extras.get("body", "")).lower():
                    raise

    def _body(self, body: dict[str, Any]) -> dict[str, Any]:
        if self.model_id:
            body["authorization_model_id"] = self.model_id
        return body

    async def read_tuples(self, obj: str) -> list[Tuple]:
        data = await self._post(self._store_path("/read"), {"tuple_key": {"object": obj}})
        return [
            Tuple(user=t["key"]["user"], relation=t["key"]["relation"], object=t["key"]["object"])
            for t in data.get("tuples", [])
        ]

    # ── Stores + models ─────────────────────────────────────────────────────────

    async def create_store(self, name: str) -> str:
        data = await self._post("/stores", {"name": name})
        return str(data["id"])

    async def write_model(self, model: dict[str, Any]) -> str:
        data = await self._post(self._store_path("/authorization-models"), model)
        return str(data["authorization_model_id"])
