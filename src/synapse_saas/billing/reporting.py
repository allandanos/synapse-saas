"""Read-model reporting over invoices and subscriptions.

Tenant-facing: per-org spend summary (billed, outstanding, over time).
Platform-facing: revenue view (MRR proxy, collected totals, status mix).
Pure queries — no mutations, safe to hit freely.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from synapse_saas.billing.models import Invoice
from synapse_saas.subscriptions.models import Subscription
from synapse_saas.subscriptions.state_machine import OCCUPYING_STATUSES


class ReportingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Tenant: what has this org been billed? ────────────────────────────────

    async def org_spend_summary(self, organization_id: UUID) -> dict[str, Any]:
        """Lifetime + current-period billing position for one org."""
        lifetime = await self._status_totals(organization_id)

        outstanding_cents = lifetime.get("open", 0)
        return {
            "organization_id": str(organization_id),
            "billed_cents": sum(lifetime.values()),
            "paid_cents": lifetime.get("paid", 0),
            "outstanding_cents": outstanding_cents,
            "void_cents": lifetime.get("void", 0),
            "by_status": lifetime,
            "currency": "PHP",
        }

    async def org_monthly_spend(self, organization_id: UUID, *, months: int = 12) -> list[dict[str, Any]]:
        """Billed totals per month (issued_at bucket), oldest → newest."""
        rows = (
            await self.session.execute(
                select(
                    func.to_char(func.date_trunc("month", Invoice.issued_at), "YYYY-MM").label("month"),
                    func.sum(Invoice.total_cents).label("total_cents"),
                    func.count().label("invoice_count"),
                )
                .where(
                    Invoice.organization_id == organization_id,
                    Invoice.status.in_(("paid", "open")),
                    Invoice.issued_at.is_not(None),
                )
                .group_by("month")
                .order_by(func.min(Invoice.issued_at))
            )
        ).all()
        return [
            {"month": r.month, "total_cents": int(r.total_cents or 0), "invoices": int(r.invoice_count)}
            for r in rows
        ]

    async def _status_totals(self, organization_id: UUID) -> dict[str, int]:
        rows = (
            await self.session.execute(
                select(Invoice.status, func.coalesce(func.sum(Invoice.total_cents), 0))
                .where(Invoice.organization_id == organization_id)
                .group_by(Invoice.status)
            )
        ).all()
        return {status: int(total or 0) for status, total in rows}

    # ── Platform: revenue view ─────────────────────────────────────────────────

    async def revenue_summary(self) -> dict[str, Any]:
        """Platform-wide numbers for the admin console.

        MRR proxy: sum of active/trialing subscriptions' snapshot prices —
        honest label (it ignores proration/coupons) but the right first number.
        """
        mrr = (
            await self.session.execute(
                select(
                    func.coalesce(
                        func.sum(
                            func.cast(
                                func.coalesce(
                                    func.jsonb_extract_path_text(Subscription.plan_snapshot, "price_cents"),
                                    "0",
                                ),
                                BigInteger(),
                            )
                        ),
                        0,
                    )
                ).where(Subscription.status.in_(OCCUPYING_STATUSES))
            )
        ).scalar_one()

        collected = (
            await self.session.execute(
                select(func.coalesce(func.sum(Invoice.total_cents), 0)).where(Invoice.status == "paid")
            )
        ).scalar_one()

        outstanding = (
            await self.session.execute(
                select(func.coalesce(func.sum(Invoice.total_cents), 0)).where(Invoice.status == "open")
            )
        ).scalar_one()

        status_mix_rows = (
            await self.session.execute(select(Invoice.status, func.count()).group_by(Invoice.status))
        ).all()

        paying_orgs = (
            await self.session.execute(
                select(func.count(func.distinct(Subscription.organization_id))).where(
                    Subscription.status.in_(OCCUPYING_STATUSES),
                    func.cast(
                        func.coalesce(
                            func.jsonb_extract_path_text(Subscription.plan_snapshot, "price_cents"),
                            "0",
                        ),
                        BigInteger(),
                    )
                    > 0,
                )
            )
        ).scalar_one()

        return {
            "mrr_proxy_cents": int(mrr or 0),
            "collected_cents": int(collected or 0),
            "outstanding_cents": int(outstanding or 0),
            "paying_organizations": int(paying_orgs or 0),
            "invoices_by_status": {status: int(count) for status, count in status_mix_rows},
            "as_of": datetime.now(UTC).isoformat(),
        }

    async def monthly_revenue(self, *, months: int = 12) -> list[dict[str, Any]]:
        """Collected (paid) revenue per month across all orgs."""
        rows = (
            await self.session.execute(
                select(
                    func.to_char(func.date_trunc("month", Invoice.paid_at), "YYYY-MM").label("month"),
                    func.sum(Invoice.total_cents).label("collected_cents"),
                    func.count().label("invoice_count"),
                )
                .where(
                    Invoice.status == "paid",
                    Invoice.paid_at.is_not(None),
                )
                .group_by("month")
                .order_by(func.min(Invoice.paid_at))
            )
        ).all()
        return [
            {
                "month": r.month,
                "collected_cents": int(r.collected_cents or 0),
                "invoices": int(r.invoice_count),
            }
            for r in rows
        ]
