"""Checkout, invoices (draft → finalize → PDF), spend reports, and the operator money routes.

Provider-dependent routes assert the documented status set for *every* provider so
the same journey runs against a manual, Stripe, or Paddle deployment.
"""

from __future__ import annotations

from httpx import AsyncClient

from tests.conformance.conftest import Tenant, assert_page, assert_problem


async def _provider(api: AsyncClient) -> str:
    return str((await api.get("/v1/meta")).json()["billing_provider"])


async def test_checkout_answers_per_provider(api: AsyncClient, tenant: Tenant) -> None:
    plans = (await api.get("/v1/plans", headers=tenant.headers)).json()
    paid = next(p["key"] for p in plans if p["price_cents"] > 0)
    res = await api.post("/v1/billing/checkout", headers=tenant.headers, json={"plan_key": paid})
    assert res.status_code == 200, res.text
    body = res.json()
    assert "url" in body or "instructions" in body or body.get("provider"), body

    confirm = await api.post("/v1/billing/checkout/confirm", headers=tenant.headers, json={"plan_key": paid})
    if await _provider(api) == "manual":
        assert confirm.status_code == 200, confirm.text
        current = (await api.get("/v1/subscription", headers=tenant.headers)).json()
        assert current["subscription"]["plan"]["key"] == paid
    else:
        assert_problem(confirm, 409, title="checkout confirm not allowed")


async def test_portal_url_per_provider(api: AsyncClient, tenant: Tenant) -> None:
    res = await api.get("/v1/billing/portal-url", headers=tenant.headers)
    if res.status_code == 200:
        assert "url" in res.json()  # hosted providers: a portal link; manual: null
    else:
        assert_problem(res, res.status_code)
        assert res.status_code in (404, 409, 422)


async def test_invoice_lifecycle(api: AsyncClient, tenant: Tenant, platform: dict[str, str]) -> None:
    assert assert_page(await api.get("/v1/billing/invoices", headers=tenant.headers)) == []

    draft = await api.post("/v1/billing/invoices/draft", headers=tenant.headers, json={})
    assert draft.status_code == 201, draft.text
    invoice = draft.json()
    assert invoice["status"] == "draft" and isinstance(invoice["lines"], list)
    invoice_id = invoice["id"]

    detail = await api.get(f"/v1/billing/invoices/{invoice_id}", headers=tenant.headers)
    assert detail.status_code == 200 and detail.json()["id"] == invoice_id

    finalized = await api.post(f"/v1/billing/invoices/{invoice_id}/finalize", headers=tenant.headers)
    assert finalized.status_code == 200, finalized.text
    assert finalized.json()["status"] in {"open", "paid"} and finalized.json()["number"]

    pdf = await api.get(f"/v1/billing/invoices/{invoice_id}/pdf", headers=tenant.headers)
    assert pdf.status_code == 200 and pdf.headers["content-type"].startswith("application/pdf")
    assert pdf.content.startswith(b"%PDF")

    listed = assert_page(await api.get("/v1/billing/invoices", headers=tenant.headers, params={"limit": 1}))
    assert listed[0]["id"] == invoice_id

    # Money movements are operator-only and invisible to tenants (ADR 0008)
    assert_problem(
        await api.post(
            f"/v1/billing/admin/invoices/{invoice_id}/pay", headers=tenant.headers, json={"amount_cents": 1}
        ),
        404,
    )
    if finalized.json()["status"] == "open" and finalized.json()["total_cents"] > 0:
        paid = await api.post(
            f"/v1/billing/admin/invoices/{invoice_id}/pay",
            headers=platform,
            json={"amount_cents": finalized.json()["total_cents"], "reference": "conformance"},
        )
        assert paid.status_code == 200 and paid.json()["status"] == "paid", paid.text
        assert_problem(await api.post(f"/v1/billing/admin/invoices/{invoice_id}/void", headers=platform), 422)
    else:  # zero-amount (free plan) invoices finalize straight to paid, or stay open at 0
        zero_pay = await api.post(
            f"/v1/billing/admin/invoices/{invoice_id}/pay", headers=platform, json={"amount_cents": 0}
        )
        assert_problem(zero_pay, 422)


async def test_void_a_draft(api: AsyncClient, tenant: Tenant, platform: dict[str, str]) -> None:
    draft = await api.post("/v1/billing/invoices/draft", headers=tenant.headers, json={})
    assert draft.status_code == 201, draft.text
    voided = await api.post(f"/v1/billing/admin/invoices/{draft.json()['id']}/void", headers=platform)
    assert voided.status_code == 200 and voided.json()["status"] == "void", voided.text


async def test_spend_and_revenue_reports(api: AsyncClient, tenant: Tenant, platform: dict[str, str]) -> None:
    summary = await api.get("/v1/billing/spend-summary", headers=tenant.headers)
    assert summary.status_code == 200, summary.text
    monthly = await api.get("/v1/billing/spend-monthly", headers=tenant.headers)
    assert monthly.status_code == 200 and isinstance(monthly.json(), list)

    assert_problem(await api.get("/v1/billing/admin/revenue-summary", headers=tenant.headers), 404)
    revenue = await api.get("/v1/billing/admin/revenue-summary", headers=platform)
    assert revenue.status_code == 200, revenue.text
    revenue_monthly = await api.get("/v1/billing/admin/revenue-monthly", headers=platform)
    assert revenue_monthly.status_code == 200 and isinstance(revenue_monthly.json(), list)


async def test_billing_webhook_rejects_unsigned_payloads(api: AsyncClient) -> None:
    provider = await _provider(api)
    res = await api.post(
        f"/v1/billing/webhooks/{provider}", content=b"{}", headers={"Content-Type": "application/json"}
    )
    assert res.status_code in (400, 401, 403, 404), res.text
    assert_problem(res, res.status_code)
