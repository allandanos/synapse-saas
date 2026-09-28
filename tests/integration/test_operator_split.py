"""Operator vs tenant: grants and money movements are platform actions.

Before: owners held entitlement:manage (self-grant `sso`, raise own limits) and
any billing:manage holder could mark their own invoice paid. Now those live on
PlatformAdminDep routes; tenant roles never carry the permission.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.integration.conftest import (
    grant_as_platform,
    pay_as_platform,
    platform_admin_headers,
    void_as_platform,
)

pytestmark = pytest.mark.pg


def org_headers(fixture: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {fixture['access_token']}", "X-Org-Id": fixture["org_id"]}


class TestTenantCannot:
    async def test_no_tenant_system_role_holds_entitlement_manage(self) -> None:
        from synapse_saas.authorization.permissions import PERMISSION_KEYS, SYSTEM_ROLES

        assert "entitlement:manage" in PERMISSION_KEYS  # still a real permission (operators)
        for role, spec in SYSTEM_ROLES.items():
            assert "entitlement:manage" not in spec["permissions"], role

    async def test_owner_cannot_self_grant_sso(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        legacy = await client.post(
            "/v1/entitlements/grants", headers=headers, json={"feature_key": "sso", "source": "enterprise"}
        )
        assert legacy.status_code in (404, 405)  # the tenant route no longer exists
        admin_path = await client.post(
            f"/v1/admin/orgs/{org_and_tokens['org_id']}/entitlements/grants",
            headers=headers,
            json={"feature_key": "sso", "source": "enterprise"},
        )
        assert admin_path.status_code == 404  # platform surfaces are invisible to tenants
        ent = (await client.get("/v1/entitlements", headers=headers)).json()
        assert "sso" not in ent["features"]

    async def test_owner_cannot_raise_own_limits(self, client: AsyncClient, org_and_tokens) -> None:
        res = await client.post(
            f"/v1/admin/orgs/{org_and_tokens['org_id']}/entitlements/grants",
            headers=org_headers(org_and_tokens),
            json={"feature_key": "limit:api_requests", "source": "addon", "limit_value": 10**9},
        )
        assert res.status_code == 404

    async def test_tenant_cannot_pay_or_void_own_invoice(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        await client.post("/v1/subscription/change", headers=headers, json={"plan_key": "pro"})
        draft = (await client.post("/v1/billing/invoices/draft", headers=headers, json={})).json()
        await client.post(f"/v1/billing/invoices/{draft['id']}/finalize", headers=headers)

        legacy_pay = await client.post(
            f"/v1/billing/invoices/{draft['id']}/pay",
            headers=headers,
            json={"amount_cents": draft["total_cents"]},
        )
        assert legacy_pay.status_code in (404, 405)
        admin_pay = await client.post(
            f"/v1/billing/admin/invoices/{draft['id']}/pay",
            headers=headers,
            json={"amount_cents": draft["total_cents"]},
        )
        assert admin_pay.status_code == 404
        admin_void = await client.post(f"/v1/billing/admin/invoices/{draft['id']}/void", headers=headers)
        assert admin_void.status_code == 404
        detail = (await client.get(f"/v1/billing/invoices/{draft['id']}", headers=headers)).json()
        assert detail["status"] == "open"


class TestOperatorCan:
    async def test_grant_then_revoke(self, client: AsyncClient, org_and_tokens) -> None:
        org_id = org_and_tokens["org_id"]
        headers = org_headers(org_and_tokens)
        grant = await grant_as_platform(
            client, org_id, {"feature_key": "sso", "source": "enterprise", "duration_days": 30}
        )
        assert grant.status_code == 201, grant.text
        assert "sso" in (await client.get("/v1/entitlements", headers=headers)).json()["features"]

        admin = await platform_admin_headers(client)
        listed = await client.get(f"/v1/admin/orgs/{org_id}/entitlements", headers=admin)
        assert listed.status_code == 200
        assert "sso" in listed.json()["features"]

        revoke = await client.delete(
            f"/v1/admin/orgs/{org_id}/entitlements/grants/{grant.json()['id']}", headers=admin
        )
        assert revoke.status_code == 204
        from synapse_saas.core.cache import VersionedCache

        await VersionedCache("entl").bump(org_id)
        assert "sso" not in (await client.get("/v1/entitlements", headers=headers)).json()["features"]

    async def test_revoke_is_scoped_to_the_path_org(self, client: AsyncClient, org_and_tokens) -> None:
        grant = await grant_as_platform(
            client, org_and_tokens["org_id"], {"feature_key": "sso", "source": "beta"}
        )
        admin = await platform_admin_headers(client)
        other_org = "00000000-0000-0000-0000-000000000001"
        res = await client.delete(
            f"/v1/admin/orgs/{other_org}/entitlements/grants/{grant.json()['id']}", headers=admin
        )
        assert res.status_code == 404

    async def test_record_payment_and_void(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        await client.post("/v1/subscription/change", headers=headers, json={"plan_key": "pro"})
        draft = (await client.post("/v1/billing/invoices/draft", headers=headers, json={})).json()
        await client.post(f"/v1/billing/invoices/{draft['id']}/finalize", headers=headers)

        paid = await pay_as_platform(
            client, draft["id"], {"amount_cents": draft["total_cents"], "reference": "wire-1"}
        )
        assert paid.status_code == 200, paid.text
        assert paid.json()["status"] == "paid"

        # paid is terminal — void is refused even for the operator
        void = await void_as_platform(client, draft["id"])
        assert void.status_code == 422

    async def test_unknown_invoice_404(self, client: AsyncClient) -> None:
        res = await pay_as_platform(client, "00000000-0000-0000-0000-000000000009", {"amount_cents": 1})
        assert res.status_code == 404
