"""Outbound webhook service: endpoint management + signed delivery with backoff."""

from __future__ import annotations

import contextlib
import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from synapse_saas.core.config import get_settings
from synapse_saas.core.errors import WebhookDeliveryNotFoundError, WebhookEndpointNotFoundError
from synapse_saas.core.logging import get_logger
from synapse_saas.core.security import sign_payload
from synapse_saas.webhooks.models import (
    DELIVERY_BACKOFF_SECONDS,
    MAX_DELIVERY_ATTEMPTS,
    WebhookDelivery,
    WebhookEndpoint,
)

logger = get_logger(__name__)

SIGNATURE_HEADER = "X-Synapse-Signature"
DELIVERY_TIMEOUT_SECONDS = 10


def _fernet() -> Fernet:
    """Fernet keyed off SYNAPSE_SECRET_KEY.

    Fernet requires 32 url-safe base64 bytes; settings secrets are arbitrary
    strings, so derive the key deterministically with SHA-256 first. Rotating
    SYNAPSE_SECRET_KEY invalidates stored webhook secrets — document that.
    """
    import base64
    import hashlib

    digest = hashlib.sha256(get_settings().secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(secret: str) -> bytes:
    return _fernet().encrypt(secret.encode("utf-8"))


def decrypt_secret(encrypted: bytes) -> str:
    return _fernet().decrypt(encrypted).decode("utf-8")


class WebhookService:
    def __init__(self, session: AsyncSession, http: httpx.AsyncClient | None = None) -> None:
        self.session = session
        self._http = http

    # ── Endpoints ───────────────────────────────────────────────────────────────

    async def create_endpoint(
        self, organization_id: UUID, *, url: str, events_filter: list[str], description: str | None
    ) -> tuple[WebhookEndpoint, str]:
        """Returns (endpoint, plaintext secret). Secret is shown exactly once."""
        import secrets

        secret = f"whsec_{secrets.token_urlsafe(24)}"
        endpoint = WebhookEndpoint(
            organization_id=organization_id,
            url=url,
            secret_encrypted=encrypt_secret(secret),
            description=description,
            events=events_filter,
        )
        self.session.add(endpoint)
        await self.session.flush()
        return endpoint, secret

    async def list_endpoints(self, organization_id: UUID) -> list[WebhookEndpoint]:
        return list(
            (
                await self.session.execute(
                    select(WebhookEndpoint).where(WebhookEndpoint.organization_id == organization_id)
                )
            )
            .scalars()
            .all()
        )

    async def get_endpoint(self, endpoint_id: UUID, organization_id: UUID) -> WebhookEndpoint:
        endpoint = await self.session.get(WebhookEndpoint, endpoint_id)
        if endpoint is None or endpoint.organization_id != organization_id:
            raise WebhookEndpointNotFoundError("Webhook endpoint not found")
        return endpoint

    async def delete_endpoint(self, endpoint_id: UUID, organization_id: UUID) -> None:
        endpoint = await self.get_endpoint(endpoint_id, organization_id)
        await self.session.delete(endpoint)

    # ── Deliveries ──────────────────────────────────────────────────────────────

    async def list_deliveries(
        self, organization_id: UUID, *, endpoint_id: UUID | None = None, limit: int = 50
    ) -> list[WebhookDelivery]:
        stmt = (
            select(WebhookDelivery)
            .where(WebhookDelivery.organization_id == organization_id)
            .order_by(WebhookDelivery.created_at.desc())
            .limit(limit)
        )
        if endpoint_id is not None:
            stmt = stmt.where(WebhookDelivery.endpoint_id == endpoint_id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def retry_delivery(self, delivery_id: UUID, organization_id: UUID) -> WebhookDelivery:
        delivery = await self.session.get(WebhookDelivery, delivery_id)
        if delivery is None or delivery.organization_id != organization_id:
            raise WebhookDeliveryNotFoundError("Delivery not found")
        delivery.status = "pending"
        delivery.attempts = 0
        delivery.next_attempt_at = datetime.now(UTC)
        return delivery

    async def deliver(self, delivery_id: UUID) -> bool:
        """Attempt one delivery. Returns success. Caller persists state changes."""
        delivery = await self.session.get(WebhookDelivery, delivery_id)
        if delivery is None:
            return False
        endpoint = await self.session.get(WebhookEndpoint, delivery.endpoint_id)
        if endpoint is None or not endpoint.is_active:
            delivery.status = "failed"
            delivery.last_error = "endpoint removed or inactive"
            return False

        payload = self.build_envelope(delivery)
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        timestamp = int(time.time())
        signature = sign_payload(body, decrypt_secret(endpoint.secret_encrypted), timestamp=timestamp)

        try:
            if self._http is None:
                self._http = httpx.AsyncClient(timeout=DELIVERY_TIMEOUT_SECONDS)
            response = await self._http.post(
                endpoint.url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    SIGNATURE_HEADER: f"t={timestamp},v1={signature}",
                },
            )
        except httpx.HTTPError as exc:
            await self._mark_failure(delivery, None, str(exc))
            return False

        if 200 <= response.status_code < 300:
            delivery.status = "delivered"
            delivery.delivered_at = datetime.now(UTC)
            delivery.last_response_code = response.status_code
            delivery.response_excerpt = response.text[:500]
            _inc_delivery("delivered")
            return True

        await self._mark_failure(delivery, response.status_code, response.text[:500])
        _inc_delivery("failed")
        return False

    @staticmethod
    def build_envelope(delivery: WebhookDelivery) -> dict[str, Any]:
        return {
            "id": str(delivery.id),
            "event_type": delivery.event_type,
            "organization_id": str(delivery.organization_id),
            "created_at": datetime.now(UTC).isoformat(),
            "data": delivery.payload,
        }

    async def _mark_failure(self, delivery: WebhookDelivery, code: int | None, error: str) -> None:
        delivery.attempts += 1
        delivery.last_response_code = code
        delivery.last_error = error[:500]
        if delivery.attempts >= min(delivery.max_attempts, MAX_DELIVERY_ATTEMPTS):
            _inc_delivery("exhausted")
            delivery.status = "exhausted"
        else:
            backoff = DELIVERY_BACKOFF_SECONDS[min(delivery.attempts - 1, len(DELIVERY_BACKOFF_SECONDS) - 1)]
            delivery.next_attempt_at = datetime.now(UTC) + timedelta(seconds=backoff)


def _inc_delivery(outcome: str) -> None:
    with contextlib.suppress(Exception):  # metrics must never fail the operation
        from synapse_saas.core import metrics

        metrics.WEBHOOK_DELIVERIES.labels(outcome=outcome).inc()
