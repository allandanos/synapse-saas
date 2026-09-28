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


async def test_validation_errors_are_422_problems(api: AsyncClient) -> None:
    res = await api.post("/v1/auth/register", json={"email": "not-an-email", "password": "x"})
    assert_problem(res, 422)
