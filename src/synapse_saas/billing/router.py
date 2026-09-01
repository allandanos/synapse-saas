"""Billing endpoints, including raw-body webhook ingest."""

from __future__ import annotations

from fastapi import APIRouter, Request, status

from synapse_saas.authorization.dependencies import require_permission
from synapse_saas.billing.protocol import WebhookRequest
from synapse_saas.billing.schemas import CheckoutRequest, CheckoutResponse, InvoiceRead, PortalUrlResponse
from synapse_saas.billing.service import BillingService
from synapse_saas.billing.webhooks import BillingWebhookService
from synapse_saas.identity.dependencies import CurrentUser, SessionDep
from synapse_saas.subscriptions.service import SubscriptionService
from synapse_saas.tenancy.dependencies import TenantDep
from synapse_saas.tenancy.service import OrganizationService

router = APIRouter(prefix="/billing", tags=["billing"])


@router.post("/checkout", response_model=CheckoutResponse)
async def start_checkout(
    body: CheckoutRequest,
    tenant: TenantDep,
    session: SessionDep,
    user: CurrentUser,
    request: Request,
) -> CheckoutResponse:
    await require_permission("billing:manage", user, session, tenant)
    org = await OrganizationService(session).get_organization(tenant.organization_id)
    plan = await SubscriptionService(session).plan_by_key(body.plan_key)
    billing = BillingService(session)

    _, result = await billing.start_checkout(
        org,
        plan,
        success_url=f"{_web_origin(request)}/dashboard/billing?checkout=success",
        cancel_url=f"{_web_origin(request)}/dashboard/billing?checkout=cancelled",
        contact_user=user,
    )
    return CheckoutResponse(
        url=result.url,
        provider=result.provider,
        manual_instructions=result.manual_instructions,
    )


@router.post("/checkout/confirm")
async def confirm_checkout(
    body: CheckoutRequest,
    tenant: TenantDep,
    session: SessionDep,
    user: CurrentUser,
) -> dict:
    """Manual-provider flow: confirm and activate immediately."""
    await require_permission("billing:manage", user, session, tenant)
    org = await OrganizationService(session).get_organization(tenant.organization_id)
    plan = await SubscriptionService(session).plan_by_key(body.plan_key)
    billing = BillingService(session)
    subscription = await billing.complete_checkout(org, plan, contact_user=user)
    return {
        "status": subscription.status,
        "plan_key": plan.key,
        "provider": billing.provider.name,
    }


@router.get("/portal-url", response_model=PortalUrlResponse)
async def portal_url(
    tenant: TenantDep, session: SessionDep, user: CurrentUser, request: Request
) -> PortalUrlResponse:
    await require_permission("billing:manage", user, session, tenant)
    org = await OrganizationService(session).get_organization(tenant.organization_id)
    url = await BillingService(session).billing_portal_url(
        org, return_url=f"{_web_origin(request)}/dashboard/billing"
    )
    return PortalUrlResponse(url=url)


@router.get("/invoices", response_model=list[InvoiceRead])
async def list_invoices(tenant: TenantDep, session: SessionDep, user: CurrentUser) -> list[InvoiceRead]:
    await require_permission("billing:read", user, session, tenant)
    invoices = await BillingService(session).invoices_for_org(tenant.organization_id)
    return [InvoiceRead.model_validate(inv) for inv in invoices]


@router.post("/webhooks/{provider}", status_code=status.HTTP_200_OK)
async def billing_webhook(provider: str, request: Request, session: SessionDep) -> dict:
    """Provider → us. Raw body read exactly once before anything parses it."""
    if provider not in {"stripe", "xendit", "paymongo", "manual"}:
        from synapse_saas.core.errors import NotFoundError

        raise NotFoundError("Unknown billing provider")

    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    service = BillingWebhookService(session)
    return await service.handle(provider, WebhookRequest(headers=headers, body=body))


def _web_origin(request: Request) -> str:
    from synapse_saas.core.config import get_settings

    settings = get_settings()
    if settings.web_origin:
        return settings.web_origin.rstrip("/")
    return str(request.base_url).rstrip("/")
