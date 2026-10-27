"""Identity: register → me → refresh → logout → login, and the problem shapes on the way."""

from __future__ import annotations

from httpx import AsyncClient

from tests.conformance.conftest import PASSWORD, Tenant, assert_problem, uid


async def test_register_me_refresh_logout_login(api: AsyncClient) -> None:
    email = f"auth-{uid()}@conformance.example.com"
    reg = await api.post(
        "/v1/auth/register", json={"email": email, "password": PASSWORD, "display_name": "Auth"}
    )
    assert reg.status_code == 201, reg.text
    body = reg.json()
    assert body["user"]["email"] == email
    assert {"access_token", "refresh_token"} <= set(body["tokens"])

    bearer = {"Authorization": f"Bearer {body['tokens']['access_token']}"}
    me = await api.get("/v1/auth/me", headers=bearer)
    assert me.status_code == 200 and me.json()["id"] == body["user"]["id"]

    refreshed = await api.post("/v1/auth/refresh", json={"refresh_token": body["tokens"]["refresh_token"]})
    assert refreshed.status_code == 200, refreshed.text
    assert {"access_token", "refresh_token", "expires_in"} <= set(refreshed.json())

    out = await api.post("/v1/auth/logout", headers=bearer)
    assert out.status_code == 204, out.text

    login = await api.post("/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    assert login.json()["tokens"]["access_token"]


async def test_duplicate_email_is_a_conflict_problem(api: AsyncClient, tenant: Tenant) -> None:
    res = await api.post(
        "/v1/auth/register",
        json={"email": tenant["email"], "password": PASSWORD, "display_name": "Dup"},
    )
    assert_problem(res, 409)


async def test_bad_password_is_401_problem(api: AsyncClient, tenant: Tenant) -> None:
    res = await api.post("/v1/auth/login", json={"email": tenant["email"], "password": "wrong-password-1"})
    assert_problem(res, 401)


async def test_missing_bearer_is_401_problem(api: AsyncClient) -> None:
    assert_problem(await api.get("/v1/auth/me"), 401)


async def test_forgot_password_never_reveals_accounts(api: AsyncClient, tenant: Tenant) -> None:
    known = await api.post("/v1/auth/forgot-password", json={"email": tenant["email"]})
    unknown = await api.post("/v1/auth/forgot-password", json={"email": f"nobody-{uid()}@example.com"})
    assert known.status_code == unknown.status_code == 202


async def test_reset_with_bogus_token_is_rejected(api: AsyncClient) -> None:
    res = await api.post("/v1/auth/reset-password", json={"token": "not-a-token", "password": PASSWORD})
    assert_problem(res, 401)


async def test_accept_invite_with_bogus_token_is_rejected(api: AsyncClient, tenant: Tenant) -> None:
    res = await api.post("/v1/auth/accept-invite", headers=tenant.bearer, json={"token": "not-a-token"})
    assert res.status_code in (401, 404), res.text
    assert_problem(res, res.status_code)


async def test_invite_preview_with_bogus_token_is_not_found(api: AsyncClient) -> None:
    # Public lookup: no bearer, no tenant. The real token only travels by email.
    res = await api.get("/v1/auth/invite", params={"token": "not-a-real-invite-token"})
    doc = assert_problem(res, 404)
    assert doc["type"].endswith("/invite_not_found"), doc


async def test_invite_preview_without_token_is_422(api: AsyncClient) -> None:
    assert_problem(await api.get("/v1/auth/invite"), 422)


async def test_validation_errors_are_422_problems(api: AsyncClient) -> None:
    res = await api.post("/v1/auth/register", json={"email": "not-an-email", "password": "x"})
    assert_problem(res, 422)


async def test_me_carries_preferences_and_patch_merges_them(api: AsyncClient, tenant: Tenant) -> None:
    me = await api.get("/v1/auth/me", headers=tenant.bearer)
    assert me.status_code == 200 and me.json()["preferences"] == {}, me.text

    tours = {"console-welcome": {"status": "completed", "version": 1}}
    first = await api.patch("/v1/auth/me", headers=tenant.bearer, json={"preferences": {"tours": tours}})
    assert first.status_code == 200 and first.json()["preferences"] == {"tours": tours}, first.text

    second = await api.patch("/v1/auth/me", headers=tenant.bearer, json={"preferences": {"theme": "light"}})
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["preferences"] == {"tours": tours, "theme": "light"}
    assert tenant["org_id"] in [org["id"] for org in body["orgs"]]

    # A listed key is replaced wholesale (the merge is top-level only): reset a namespace with {}.
    third = await api.patch("/v1/auth/me", headers=tenant.bearer, json={"preferences": {"tours": {}}})
    assert third.status_code == 200, third.text
    assert third.json()["preferences"] == {"tours": {}, "theme": "light"}


async def test_me_orgs_carry_the_callers_permission_keys(api: AsyncClient, tenant: Tenant) -> None:
    """Each org on /me carries the caller's effective RBAC set — what the console gates on."""
    me = await api.get("/v1/auth/me", headers=tenant.bearer)
    assert me.status_code == 200, me.text
    org = next(o for o in me.json()["orgs"] if o["id"] == tenant["org_id"])
    keys = org["permission_keys"]
    assert keys == sorted(keys)
    assert {"org:read", "member:read", "billing:read"} <= set(keys)
    assert "entitlement:manage" not in keys  # operator-only, no tenant role holds it


async def test_patch_me_without_bearer_is_401_problem(api: AsyncClient) -> None:
    assert_problem(await api.patch("/v1/auth/me", json={"preferences": {"theme": "light"}}), 401)


async def test_patch_me_with_invalid_key_is_422_problem(api: AsyncClient, tenant: Tenant) -> None:
    res = await api.patch("/v1/auth/me", headers=tenant.bearer, json={"preferences": {"Not A Key": 1}})
    doc = assert_problem(res, 422)
    assert doc["type"].endswith("/validation_failed"), doc


async def test_patch_me_over_the_patch_byte_cap_is_422_problem(api: AsyncClient, tenant: Tenant) -> None:
    # 16 KiB per request, counted as compact UTF-8 JSON bytes.
    big = {"preferences": {"big": "x" * 17 * 1024}}
    res = await api.patch("/v1/auth/me", headers=tenant.bearer, json=big)
    doc = assert_problem(res, 422)
    assert doc["type"].endswith("/validation_failed"), doc


async def test_patch_me_with_an_api_key_is_403_problem(api: AsyncClient, tenant: Tenant) -> None:
    # Preferences are a person's UI state: an organization's `sk_` key cannot write them.
    created = await api.post("/v1/api-keys", headers=tenant.headers, json={"name": "conf", "scopes": []})
    assert created.status_code == 201, created.text
    key = created.json()["key"]
    res = await api.patch(
        "/v1/auth/me", headers={"Authorization": f"Bearer {key}"}, json={"preferences": {"theme": "dark"}}
    )
    doc = assert_problem(res, 403)
    assert doc["type"].endswith("/permission_denied"), doc


async def test_get_me_with_an_api_key_is_403_problem(api: AsyncClient, tenant: Tenant) -> None:
    # An `sk_` key is an organization's credential, not a person: there is no profile to read.
    created = await api.post("/v1/api-keys", headers=tenant.headers, json={"name": "conf-me", "scopes": []})
    assert created.status_code == 201, created.text
    key = created.json()["key"]
    res = await api.get("/v1/auth/me", headers={"Authorization": f"Bearer {key}"})
    doc = assert_problem(res, 403)
    assert doc["type"].endswith("/permission_denied"), doc
