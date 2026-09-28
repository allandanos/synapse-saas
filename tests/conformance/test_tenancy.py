"""Organizations, memberships, org switching, and operator suspension."""

from __future__ import annotations

from httpx import AsyncClient

from tests.conformance.conftest import Tenant, assert_envelope, assert_problem, uid


async def test_org_lifecycle(api: AsyncClient, tenant: Tenant) -> None:
    orgs = assert_envelope(await api.get("/v1/orgs", headers=tenant.bearer))
    assert [o["id"] for o in orgs["data"]] == [tenant["org_id"]] and orgs["meta"]["total"] == 1

    current = await api.get("/v1/orgs/current", headers=tenant.headers)
    assert current.status_code == 200 and current.json()["slug"] == tenant["slug"]

    renamed = await api.patch("/v1/orgs/current", headers=tenant.headers, json={"name": "Renamed"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "Renamed"

    switched = await api.post(
        "/v1/auth/switch-org", headers=tenant.bearer, json={"organization_id": tenant["org_id"]}
    )
    assert switched.status_code == 200, switched.text
    assert {"access_token", "token_type", "expires_in"} <= set(switched.json())
    # The org claim now resolves the tenant without any header
    scoped = {"Authorization": f"Bearer {switched.json()['access_token']}"}
    assert (await api.get("/v1/orgs/current", headers=scoped)).json()["id"] == tenant["org_id"]


async def test_current_org_needs_a_tenant(api: AsyncClient, tenant: Tenant) -> None:
    """No X-Org-Id and no default org claim ⇒ a problem, never a cross-tenant guess."""
    res = await api.get("/v1/orgs/current", headers={**tenant.bearer, "X-Org-Id": str(uid()) * 4})
    assert res.status_code in (400, 404, 422), res.text


async def test_membership_lifecycle(api: AsyncClient, tenant: Tenant) -> None:
    members = assert_envelope(await api.get("/v1/orgs/current/members", headers=tenant.headers))
    assert members["meta"]["total"] == 1
    owner = members["data"][0]
    assert "owner" in owner["role_keys"]

    email = f"invitee-{uid()}@conformance.example.com"
    invited = await api.post(
        "/v1/orgs/current/members/invite",
        headers=tenant.headers,
        json={"email": email, "role_keys": ["member"]},
    )
    assert invited.status_code == 201, invited.text
    membership_id = invited.json()["id"]
    assert invited.json()["status"] == "invited"
    assert invited.json()["role_keys"] == ["member"]
    assert "invite_token" not in invited.text, "invite tokens travel by email only"

    again = await api.post(
        "/v1/orgs/current/members/invite",
        headers=tenant.headers,
        json={"email": email, "role_keys": ["member"]},
    )
    assert_problem(again, 409, title="conflict")

    promoted = await api.patch(
        f"/v1/memberships/{membership_id}", headers=tenant.headers, json={"role_keys": ["developer"]}
    )
    assert promoted.status_code == 200 and promoted.json()["role_keys"] == ["developer"]

    after = assert_envelope(
        await api.get("/v1/orgs/current/members", headers=tenant.headers, params={"limit": 1})
    )
    assert after["meta"]["total"] == 2 and len(after["data"]) == 1

    removed = await api.delete(f"/v1/memberships/{membership_id}", headers=tenant.headers)
    assert removed.status_code == 204
    assert_problem(await api.delete(f"/v1/memberships/{membership_id}", headers=tenant.headers), 404)


async def test_other_tenants_rows_are_404(api: AsyncClient, tenant: Tenant) -> None:
    from tests.conformance.conftest import make_tenant

    other = await make_tenant(api, label="other")
    members = await api.get("/v1/orgs/current/members", headers=other.headers)
    their_membership = members.json()["data"][0]["id"]
    res = await api.patch(
        f"/v1/memberships/{their_membership}", headers=tenant.headers, json={"role_keys": ["member"]}
    )
    assert_problem(res, 404)


async def test_operator_can_suspend_and_unsuspend(
    api: AsyncClient, tenant: Tenant, platform: dict[str, str]
) -> None:
    denied = await api.post(f"/v1/orgs/{tenant['org_id']}/suspend", headers=tenant.headers)
    assert_problem(denied, 404)  # operator routes are invisible to tenants (ADR 0008)

    assert (await api.post(f"/v1/orgs/{tenant['org_id']}/suspend", headers=platform)).status_code == 204
    while_suspended = await api.get("/v1/orgs/current", headers=tenant.headers)
    doc = assert_problem(while_suspended, 403, title="organization suspended")
    assert doc["organization_id"] == tenant["org_id"]

    assert (await api.delete(f"/v1/orgs/{tenant['org_id']}/suspend", headers=platform)).status_code == 204
    assert (await api.get("/v1/orgs/current", headers=tenant.headers)).status_code == 200
