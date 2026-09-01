"""Webhook endpoint + delivery endpoints (tenant-facing)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, status

from synapse_saas.authorization.dependencies import require_permission
from synapse_saas.identity.dependencies import CurrentUser, SessionDep
from synapse_saas.tenancy.dependencies import TenantDep
from synapse_saas.webhooks.schemas import (
    WebhookDeliveryRead,
    WebhookEndpointCreate,
    WebhookEndpointCreated,
    WebhookEndpointRead,
)
from synapse_saas.webhooks.service import WebhookService

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.get("/endpoints", response_model=list[WebhookEndpointRead])
async def list_endpoints(
    tenant: TenantDep, session: SessionDep, user: CurrentUser
) -> list[WebhookEndpointRead]:
    await require_permission("webhook:manage", user, session, tenant)
    endpoints = await WebhookService(session).list_endpoints(tenant.organization_id)
    return [WebhookEndpointRead.model_validate(e) for e in endpoints]


@router.post("/endpoints", response_model=WebhookEndpointCreated, status_code=status.HTTP_201_CREATED)
async def create_endpoint(
    body: WebhookEndpointCreate, tenant: TenantDep, session: SessionDep, user: CurrentUser
) -> WebhookEndpointCreated:
    await require_permission("webhook:manage", user, session, tenant)
    endpoint, secret = await WebhookService(session).create_endpoint(
        tenant.organization_id,
        url=str(body.url),
        events_filter=body.events,
        description=body.description,
    )
    # Build the response shape explicitly: the ORM object has no `secret`
    # column (it's encrypted and never returned after creation).
    base = WebhookEndpointRead.model_validate(endpoint)
    return WebhookEndpointCreated(**base.model_dump(), secret=secret)


@router.delete("/endpoints/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_endpoint(
    endpoint_id: UUID, tenant: TenantDep, session: SessionDep, user: CurrentUser
) -> None:
    await require_permission("webhook:manage", user, session, tenant)
    await WebhookService(session).delete_endpoint(endpoint_id, tenant.organization_id)


@router.get("/deliveries", response_model=list[WebhookDeliveryRead])
async def list_deliveries(
    tenant: TenantDep,
    session: SessionDep,
    user: CurrentUser,
    endpoint_id: UUID | None = None,
    limit: int = Query(50, ge=1, le=100),
) -> list[WebhookDeliveryRead]:
    await require_permission("webhook:manage", user, session, tenant)
    deliveries = await WebhookService(session).list_deliveries(
        tenant.organization_id, endpoint_id=endpoint_id, limit=limit
    )
    return [WebhookDeliveryRead.model_validate(d) for d in deliveries]


@router.post("/deliveries/{delivery_id}/retry", response_model=WebhookDeliveryRead)
async def retry_delivery(
    delivery_id: UUID, tenant: TenantDep, session: SessionDep, user: CurrentUser
) -> WebhookDeliveryRead:
    await require_permission("webhook:manage", user, session, tenant)
    delivery = await WebhookService(session).retry_delivery(delivery_id, tenant.organization_id)
    return WebhookDeliveryRead.model_validate(delivery)
