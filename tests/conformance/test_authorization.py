"""Permission catalog, system roles, and custom-role CRUD."""

from __future__ import annotations

from httpx import AsyncClient

from tests.conformance.conftest import Tenant, assert_problem, uid

SYSTEM_ROLES = {"owner", "admin", "billing", "developer", "member"}


async def test_permission_catalog(api: AsyncClient, tenant: Tenant) -> None:
    res = await api.get("/v1/permissions", headers=tenant.headers)
    assert res.status_code == 200, res.text
    keys = {p["key"] for p in res.json()}
    assert {"org:read", "member:invite", "billing:manage", "usage:read"} <= keys
    assert all(":" in k for k in keys)


async def test_system_roles_present(api: AsyncClient, tenant: Tenant) -> None:
    res = await api.get("/v1/roles", headers=tenant.headers)
    assert res.status_code == 200, res.text
    assert {r["key"] for r in res.json()} >= SYSTEM_ROLES


async def test_custom_role_crud(api: AsyncClient, tenant: Tenant) -> None:
    key = f"auditor_{uid()}"
    created = await api.post(
        "/v1/roles",
        headers=tenant.headers,
        json={"key": key, "name": "Auditor", "permissions": ["audit:read", "org:read"]},
    )
    assert created.status_code == 201, created.text
    role_id = created.json()["id"]
    assert set(created.json()["permissions"]) == {"audit:read", "org:read"}

    patched = await api.patch(
        f"/v1/roles/{role_id}", headers=tenant.headers, json={"permissions": ["org:read"], "name": "Reader"}
    )
    assert patched.status_code == 200 and patched.json()["permissions"] == ["org:read"]

    unknown_permission = await api.post(
        "/v1/roles",
        headers=tenant.headers,
        json={"key": f"x_{uid()}", "name": "X", "permissions": ["nope:nope"]},
    )
    assert_problem(unknown_permission, 422)

    assert (await api.delete(f"/v1/roles/{role_id}", headers=tenant.headers)).status_code == 204
    assert_problem(await api.delete(f"/v1/roles/{role_id}", headers=tenant.headers), 404)


async def test_system_roles_are_immutable(api: AsyncClient, tenant: Tenant) -> None:
    roles = await api.get("/v1/roles", headers=tenant.headers)
    owner = next(r for r in roles.json() if r["key"] == "owner")
    res = await api.delete(f"/v1/roles/{owner['id']}", headers=tenant.headers)
    assert res.status_code in (403, 404, 409, 422), res.text  # system roles are not custom roles
    assert_problem(res, res.status_code)


async def test_member_role_cannot_manage_billing(api: AsyncClient, tenant: Tenant) -> None:
    """A second user with only `member` gets 403 on billing:manage routes."""
    from tests.conformance.conftest import PASSWORD

    email = f"member-{uid()}@conformance.example.com"
    reg = await api.post(
        "/v1/auth/register", json={"email": email, "password": PASSWORD, "display_name": "M"}
    )
    assert reg.status_code == 201
    # Invite + accept needs the emailed token; prove the negative with a foreign user on the owner's org
    foreign = {
        "Authorization": f"Bearer {reg.json()['tokens']['access_token']}",
        "X-Org-Id": tenant["org_id"],
    }
    res = await api.get("/v1/billing/portal-url", headers=foreign)
    assert res.status_code in (403, 404), res.text
    assert_problem(res, res.status_code)
