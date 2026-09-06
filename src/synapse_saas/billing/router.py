"""Billing endpoints, including raw-body webhook ingest."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, Response, status

from synapse_saas.authorization.dependencies import require_permission
from synapse_saas.billing.invoice_pdf import render_invoice_pdf
from synapse_saas.billing.invoicing import InvoicingService
from synapse_saas.billing.protocol import WebhookRequest
from synapse_saas.billing.reporting import ReportingService
from synapse_saas.billing.schemas import (
    CheckoutRequest,
    CheckoutResponse,
    InvoiceDetailRead,
    InvoiceDraftRequest,
    InvoiceLineRead,
    InvoiceRead,
    PaymentRecordRequest,
    PortalUrlResponse,
)
from synapse_saas.billing.service import BillingService
from synapse_saas.billing.webhooks import BillingWebhookService
from synapse_saas.identity.dependencies import CurrentUser, SessionDep
from synapse_saas.subscriptions.service import SubscriptionService
from synapse_saas.tenancy.dependencies import PlatformAdminDep, TenantDep
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
) -> dict[str, Any]:
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


# ── Reporting (tenant spend + platform revenue) ──────────────────────────────


@router.get("/spend-summary")
async def spend_summary(tenant: TenantDep, session: SessionDep, user: CurrentUser) -> dict[str, Any]:
    """This org's lifetime billing position: billed/paid/outstanding by status."""
    await require_permission("billing:read", user, session, tenant)
    return await ReportingService(session).org_spend_summary(tenant.organization_id)


@router.get("/spend-monthly")
async def spend_monthly(tenant: TenantDep, session: SessionDep, user: CurrentUser) -> list[dict[str, Any]]:
    await require_permission("billing:read", user, session, tenant)
    return await ReportingService(session).org_monthly_spend(tenant.organization_id)


@router.get("/admin/revenue-summary")
async def revenue_summary(platform: PlatformAdminDep, session: SessionDep) -> dict[str, Any]:
    """Platform-wide revenue view (MRR proxy, collected, outstanding)."""
    return await ReportingService(session).revenue_summary()


@router.get("/admin/revenue-monthly")
async def revenue_monthly(platform: PlatformAdminDep, session: SessionDep) -> list[dict[str, Any]]:
    return await ReportingService(session).monthly_revenue()


# ── Framework-native invoicing (manual/enterprise path) ─────────────────────


@router.post("/invoices/draft", response_model=InvoiceDetailRead, status_code=status.HTTP_201_CREATED)
async def draft_invoice(
    body: InvoiceDraftRequest,
    tenant: TenantDep,
    session: SessionDep,
    user: CurrentUser,
) -> InvoiceDetailRead:
    """Generate (or return the existing) draft for the period: plan + overage lines."""
    await require_permission("billing:manage", user, session, tenant)
    period = _parse_period(body.period)
    invoice = await InvoicingService(session).draft_for_org(
        tenant.organization_id, period=period, created_by_user_id=user.id
    )
    return await _detail(session, invoice)


@router.post("/invoices/{invoice_id}/finalize", response_model=InvoiceDetailRead)
async def finalize_invoice(
    invoice_id: UUID,
    tenant: TenantDep,
    session: SessionDep,
    user: CurrentUser,
) -> InvoiceDetailRead:
    """Assign a number, lock amounts, move to open. Outbox emits for webhooks/email."""
    await require_permission("billing:manage", user, session, tenant)
    invoice = await InvoicingService(session).finalize(invoice_id, tenant.organization_id)
    return await _detail(session, invoice)


@router.post("/invoices/{invoice_id}/pay", response_model=InvoiceDetailRead)
async def record_payment(
    invoice_id: UUID,
    body: PaymentRecordRequest,
    tenant: TenantDep,
    session: SessionDep,
    user: CurrentUser,
) -> InvoiceDetailRead:
    """Record an external payment (bank transfer, check, cash) against an open invoice."""
    await require_permission("billing:manage", user, session, tenant)
    invoice = await InvoicingService(session).record_payment(
        invoice_id,
        tenant.organization_id,
        amount_cents=body.amount_cents,
        reference=body.reference,
    )
    return await _detail(session, invoice)


@router.post("/invoices/{invoice_id}/void", response_model=InvoiceDetailRead)
async def void_invoice(
    invoice_id: UUID,
    tenant: TenantDep,
    session: SessionDep,
    user: CurrentUser,
) -> InvoiceDetailRead:
    await require_permission("billing:manage", user, session, tenant)
    invoice = await InvoicingService(session).void(invoice_id, tenant.organization_id)
    return await _detail(session, invoice)


@router.get("/invoices/{invoice_id}/pdf")
async def download_invoice_pdf(
    invoice_id: UUID,
    tenant: TenantDep,
    session: SessionDep,
    user: CurrentUser,
) -> Response:
    """Stream the framework-rendered PDF for an invoice."""
    from fastapi.responses import Response as FastResponse

    await require_permission("billing:read", user, session, tenant)
    service = InvoicingService(session)
    invoice = await service.get(invoice_id, tenant.organization_id)
    lines = await service.lines_for(invoice_id, tenant.organization_id)

    from synapse_saas.tenancy.models import Organization

    org = await session.get(Organization, tenant.organization_id)
    org_name = org.name if org else "Unknown Organization"

    from synapse_saas.core.config import get_settings

    settings = get_settings()
    billing_email = None
    if invoice.billing_customer_id is not None:
        from synapse_saas.billing.models import BillingCustomer

        customer = await session.get(BillingCustomer, invoice.billing_customer_id)
        billing_email = str(customer.email) if customer and customer.email else None

    pdf_bytes = render_invoice_pdf(
        invoice,
        lines,
        org_name=org_name,
        billing_email=billing_email,
        pay_to_instructions=settings.manual_pay_to_instructions or None,
    )
    filename = f"invoice-{invoice.number or invoice.id}.pdf"
    return FastResponse(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/invoices/{invoice_id}", response_model=InvoiceDetailRead)
async def get_invoice_detail(
    invoice_id: UUID, tenant: TenantDep, session: SessionDep, user: CurrentUser
) -> InvoiceDetailRead:
    await require_permission("billing:read", user, session, tenant)
    invoice = await InvoicingService(session).get(invoice_id, tenant.organization_id)
    return await _detail(session, invoice)


async def _detail(session: SessionDep, invoice: Any) -> InvoiceDetailRead:
    service = InvoicingService(session)
    lines = await service.lines_for(invoice.id, invoice.organization_id)
    base = InvoiceRead.model_validate(invoice)
    return InvoiceDetailRead(
        **base.model_dump(),
        lines=[InvoiceLineRead.model_validate(line) for line in lines],
    )


def _parse_period(raw: str | None) -> date | None:
    if raw is None:
        return None
    from datetime import datetime as _dt

    return _dt.strptime(raw, "%Y-%m").date().replace(day=1)


@router.post("/webhooks/{provider}", status_code=status.HTTP_200_OK)
async def billing_webhook(provider: str, request: Request, session: SessionDep) -> dict[str, Any]:
    """Provider → us. Raw body read exactly once before anything parses it."""
    if provider not in {"stripe", "xendit", "paymongo", "paddle", "manual"}:
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
