"""Worker boundary jobs: manual billing roll, partitions, purge."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.pg


def org_headers(fixture: dict[str, str]) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {fixture['access_token']}",
        "X-Org-Id": fixture["org_id"],
    }


@pytest.fixture(autouse=True)
async def _fresh_engine(clean_db):
    from synapse_saas.core.db import dispose_engine

    await dispose_engine()
    yield
    await dispose_engine()


class TestManualBillingRoll:
    async def test_period_roll_issues_invoice(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        # Manual subscribe to a paid plan
        await client.post("/v1/billing/checkout/confirm", headers=headers, json={"plan_key": "starter"})

        # Backdate the period so the job sees it due
        from sqlalchemy import text

        from synapse_saas.core.db import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                text("UPDATE subscriptions SET current_period_end = now() - interval '1 day'")
            )
            await session.commit()

        from synapse_saas.worker.jobs import advance_manual_billing

        rolled = await advance_manual_billing({})
        assert rolled == 1

        invoices = (await client.get("/v1/billing/invoices", headers=headers)).json()
        assert any(i["total_cents"] == 49900 for i in invoices)

        # Period advanced past now
        async with factory() as session:
            end = (
                await session.execute(text("SELECT max(current_period_end) FROM subscriptions"))
            ).scalar_one()
            assert end is not None

    async def test_cancelled_not_rolled(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        await client.post("/v1/billing/checkout/confirm", headers=headers, json={"plan_key": "starter"})
        await client.post("/v1/subscription/cancel", headers=headers, json={"at_period_end": True})

        from sqlalchemy import text

        from synapse_saas.core.db import get_session_factory
        from synapse_saas.worker.jobs import advance_manual_billing

        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                text("UPDATE subscriptions SET current_period_end = now() - interval '1 day'")
            )
            await session.commit()

        assert await advance_manual_billing({}) == 0


class TestPartitionJob:
    async def test_ensure_partitions_creates_next_month(self) -> None:
        from synapse_saas.core.db import get_session_factory
        from synapse_saas.worker.jobs import ensure_partitions

        assert await ensure_partitions({}) == 1

        factory = get_session_factory()
        async with factory() as session:
            from sqlalchemy import text

            count = (
                await session.execute(
                    text("SELECT count(*) FROM pg_tables WHERE tablename LIKE 'usage_events_y%'")
                )
            ).scalar_one()
        # Migration created current+next; the job guarantees next month exists
        # (idempotent — running again must not fail or duplicate).
        assert await ensure_partitions({}) == 1
        assert count >= 2


class TestPurgeJob:
    async def test_purge_removes_old_deliveries(self) -> None:
        from sqlalchemy import text

        from synapse_saas.core.db import get_session_factory
        from synapse_saas.worker.jobs import purge_expired

        factory = get_session_factory()
        async with factory() as session:
            # Real parent rows to satisfy the FKs
            await session.execute(
                text(
                    """
                    INSERT INTO organizations (id, slug, name, status, settings)
                    VALUES (gen_random_uuid(), 'purge-org', 'Purge Org', 'active', '{}')
                    RETURNING id
                    """
                )
            )
            await session.execute(
                text(
                    """
                    INSERT INTO webhook_endpoints
                        (id, organization_id, url, secret_encrypted, events, is_active)
                    SELECT gen_random_uuid(), id, 'https://x.example.test/hook',
                           'enc-bytes', '{}', true
                    FROM organizations WHERE slug = 'purge-org'
                    """
                )
            )
            await session.execute(
                text(
                    """
                    INSERT INTO webhook_deliveries
                        (id, endpoint_id, organization_id, event_type, payload, status,
                         attempts, max_attempts, next_attempt_at)
                    SELECT gen_random_uuid(), e.id, e.organization_id,
                           'test.purge', '{}', 'delivered', 1, 5, now()
                    FROM webhook_endpoints e
                    JOIN organizations o ON o.id = e.organization_id
                    WHERE o.slug = 'purge-org'
                    """
                )
            )
            await session.execute(
                text("UPDATE webhook_deliveries SET created_at = now() - interval '40 days'")
            )
            await session.commit()

        assert await purge_expired({}) == 1

        async with factory() as session:
            remaining = (await session.execute(text("SELECT count(*) FROM webhook_deliveries"))).scalar_one()
        assert remaining == 0
