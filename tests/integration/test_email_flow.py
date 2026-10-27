"""Email flow end-to-end: outbox carries invitations and reset links."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.integration.conftest import owner_session_factory

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


class TestInviteEmail:
    async def test_invite_queues_email_event(self, client: AsyncClient, org_and_tokens) -> None:
        """member.invited lands in the outbox with the invite token for the worker."""
        res = await client.post(
            "/v1/orgs/current/members/invite",
            headers=org_headers(org_and_tokens),
            json={"email": "invitee@example.com"},
        )
        assert res.status_code == 201

        from sqlalchemy import text

        async with owner_session_factory()() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT event_type, payload, audience FROM outbox_events "
                        "WHERE event_type = 'member.invite_email' ORDER BY created_at DESC LIMIT 1"
                    )
                )
            ).first()
            public = (
                await session.execute(
                    text(
                        "SELECT payload, audience FROM outbox_events "
                        "WHERE event_type = 'member.invited' ORDER BY created_at DESC LIMIT 1"
                    )
                )
            ).first()
        assert row is not None
        payload = row.payload
        assert payload["email"] == "invitee@example.com"
        assert "invite_token" in payload
        assert len(payload["invite_token"]) >= 32  # a usable link, not the hash
        assert row.audience == "internal"  # email only — never fanned out to webhooks
        assert public is not None and public.audience == "public"
        assert "invite_token" not in public.payload  # the public event carries no credential

    async def test_worker_dispatch_sends_invite_email(
        self, client: AsyncClient, org_and_tokens, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from synapse_saas.notifications import handlers
        from synapse_saas.worker.jobs import dispatch_outbox

        sent: list[dict[str, str]] = []

        async def fake_send(*, to: str, subject: str, body: str) -> None:
            sent.append({"to": to, "subject": subject, "body": body})

        monkeypatch.setattr(handlers, "get_notifier", lambda: type("N", (), {"send": fake_send}))

        await client.post(
            "/v1/orgs/current/members/invite",
            headers=org_headers(org_and_tokens),
            json={"email": "flow@example.com"},
        )
        count = await dispatch_outbox({})
        assert count >= 1
        assert any(i["to"] == "flow@example.com" for i in sent)
        invite = next(i for i in sent if i["to"] == "flow@example.com")
        assert "invite" in invite["subject"].lower()


async def _latest_invite_token(email: str) -> str:
    """The clear invite token rides only the internal email event."""
    from sqlalchemy import text

    async with owner_session_factory()() as session:
        payload = (
            await session.execute(
                text(
                    "SELECT payload FROM outbox_events WHERE event_type = 'member.invite_email' "
                    "AND payload->>'email' = :email ORDER BY created_at DESC LIMIT 1"
                ),
                {"email": email},
            )
        ).scalar_one()
    token: str = payload["invite_token"]
    return token


class TestInvitePreview:
    async def test_preview_names_the_org_until_the_invite_is_accepted(
        self, client: AsyncClient, org_and_tokens
    ) -> None:
        invited = await client.post(
            "/v1/orgs/current/members/invite",
            headers=org_headers(org_and_tokens),
            json={"email": "joiner@example.com", "role_keys": ["member", "developer"]},
        )
        assert invited.status_code == 201, invited.text
        token = await _latest_invite_token("joiner@example.com")

        preview = await client.get("/v1/auth/invite", params={"token": token})
        assert preview.status_code == 200, preview.text
        assert preview.json() == {
            "organization": {"id": org_and_tokens["org_id"], "slug": "test-org", "name": "Test Org"},
            "invited_email": "joiner@example.com",
            "role_keys": ["developer", "member"],
        }
        # Previewing does not consume the token
        again = await client.get("/v1/auth/invite", params={"token": token})
        assert again.status_code == 200, again.text

        registered = await client.post(
            "/v1/auth/register",
            json={"email": "joiner@example.com", "password": "password12345", "display_name": "Joiner"},
        )
        assert registered.status_code == 201, registered.text
        bearer = {"Authorization": f"Bearer {registered.json()['tokens']['access_token']}"}
        accepted = await client.post("/v1/auth/accept-invite", headers=bearer, json={"token": token})
        assert accepted.status_code == 200, accepted.text
        assert accepted.json() == {"organization_id": org_and_tokens["org_id"], "status": "active"}

        used = await client.get("/v1/auth/invite", params={"token": token})
        assert used.status_code == 404, used.text
        assert used.json()["type"].endswith("/invite_not_found")

    async def test_unknown_token_is_invite_not_found(self, client: AsyncClient) -> None:
        res = await client.get("/v1/auth/invite", params={"token": "x" * 43})
        assert res.status_code == 404, res.text
        assert res.json()["status"] == 404
        assert res.json()["type"].endswith("/invite_not_found")

    async def test_missing_or_short_token_is_a_validation_problem(self, client: AsyncClient) -> None:
        missing = await client.get("/v1/auth/invite")
        short = await client.get("/v1/auth/invite", params={"token": "short"})
        for res in (missing, short):
            assert res.status_code == 422, res.text
            assert res.json()["status"] == 422


class TestPasswordResetEmail:
    async def test_reset_link_queued_and_emailed(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await client.post(
            "/v1/auth/register",
            json={
                "email": "resetflow@example.com",
                "password": "password12345",
                "display_name": "R",
            },
        )

        from synapse_saas.notifications import handlers
        from synapse_saas.worker.jobs import dispatch_outbox

        sent: list[dict[str, str]] = []

        async def fake_send(*, to: str, subject: str, body: str) -> None:
            sent.append({"to": to, "subject": subject, "body": body})

        monkeypatch.setattr(handlers, "get_notifier", lambda: type("N", (), {"send": fake_send}))

        res = await client.post("/v1/auth/forgot-password", json={"email": "resetflow@example.com"})
        assert res.status_code == 202
        # Opaque: unknown email produces the same response, no event
        unknown = await client.post("/v1/auth/forgot-password", json={"email": "ghost@example.com"})
        assert unknown.status_code == 202

        await dispatch_outbox({})
        resets = [s for s in sent if "reset" in s["subject"].lower()]
        assert len(resets) == 1  # exactly one email — ghost sent none
        assert resets[0]["to"] == "resetflow@example.com"

    async def test_token_in_email_is_valid(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The token the worker emails actually resets the password."""
        await client.post(
            "/v1/auth/register",
            json={
                "email": "tokcheck@example.com",
                "password": "password12345",
                "display_name": "T",
            },
        )
        from synapse_saas.notifications import handlers
        from synapse_saas.worker.jobs import dispatch_outbox

        bodies: list[str] = []

        async def fake_send(*, to: str, subject: str, body: str) -> None:
            bodies.append(body)

        monkeypatch.setattr(handlers, "get_notifier", lambda: type("N", (), {"send": fake_send}))
        await client.post("/v1/auth/forgot-password", json={"email": "tokcheck@example.com"})
        await dispatch_outbox({})

        reset_body = next(b for b in bodies if "reset" in b.lower() or "Reset" in b)
        import re

        token_match = re.search(r"reset=([A-Za-z0-9_-]+)", reset_body)
        assert token_match, f"no token link in email body: {reset_body[:120]}"
        token = token_match.group(1)

        done = await client.post(
            "/v1/auth/reset-password",
            json={"token": token, "password": "new-password-123"},
        )
        assert done.status_code == 200, done.text
        login = await client.post(
            "/v1/auth/login",
            json={"email": "tokcheck@example.com", "password": "new-password-123"},
        )
        assert login.status_code == 200


class TestAcceptInviteEndpoint:
    async def test_register_with_invite_joins_org(self, client: AsyncClient, org_and_tokens) -> None:
        """The emailed token + new registration ⇒ membership in the org."""
        invite = await client.post(
            "/v1/orgs/current/members/invite",
            headers={
                "Authorization": f"Bearer {org_and_tokens['access_token']}",
                "X-Org-Id": org_and_tokens["org_id"],
            },
            json={"email": "joiner@example.com"},
        )
        assert invite.status_code == 201

        # Pull the token from the outbox (what the worker emails)
        from sqlalchemy import text

        async with owner_session_factory()() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT payload FROM outbox_events "
                        "WHERE event_type = 'member.invite_email' ORDER BY created_at DESC LIMIT 1"
                    )
                )
            ).first()
        token = row.payload["invite_token"]

        reg = await client.post(
            "/v1/auth/register",
            json={
                "email": "joiner@example.com",
                "password": "password12345",
                "display_name": "J",
            },
        )
        assert reg.status_code == 201
        joiner_token = reg.json()["tokens"]["access_token"]

        accepted = await client.post(
            "/v1/auth/accept-invite",
            headers={"Authorization": f"Bearer {joiner_token}"},
            json={"token": token},
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["status"] == "active"
        assert accepted.json()["organization_id"] == org_and_tokens["org_id"]

        # Token is single-use
        replay = await client.post(
            "/v1/auth/accept-invite",
            headers={"Authorization": f"Bearer {joiner_token}"},
            json={"token": token},
        )
        assert replay.status_code == 404

    async def test_garbage_token_404(self, client: AsyncClient, org_and_tokens) -> None:
        res = await client.post(
            "/v1/auth/accept-invite",
            headers={"Authorization": f"Bearer {org_and_tokens['access_token']}"},
            json={"token": "n" * 40},
        )
        assert res.status_code == 404


class TestInviteAcceptance:
    """`POST /v1/auth/accept-invite` joins only the person the invite was sent to."""

    async def _register_and_login(self, client: AsyncClient, email: str) -> dict[str, str]:
        registered = await client.post(
            "/v1/auth/register",
            json={"email": email, "password": "password12345", "display_name": email.split("@", 1)[0]},
        )
        assert registered.status_code == 201, registered.text
        login = await client.post("/v1/auth/login", json={"email": email, "password": "password12345"})
        assert login.status_code == 200, login.text
        return {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"}

    async def test_another_user_cannot_accept_with_the_token(
        self, client: AsyncClient, org_and_tokens
    ) -> None:
        invited = await client.post(
            "/v1/orgs/current/members/invite",
            headers=org_headers(org_and_tokens),
            json={"email": "intended@example.com", "role_keys": ["member"]},
        )
        assert invited.status_code == 201, invited.text
        token = await _latest_invite_token("intended@example.com")
        stranger = await self._register_and_login(client, "stranger@example.com")

        denied = await client.post("/v1/auth/accept-invite", headers=stranger, json={"token": token})
        assert denied.status_code == 403, denied.text
        assert denied.json()["type"].endswith("/permission_denied"), denied.text
        assert "email" in denied.json()["detail"].lower()

        # The token is not consumed by a refused attempt: the invitee can still use it.
        preview = await client.get("/v1/auth/invite", params={"token": token})
        assert preview.status_code == 200, preview.text
        invitee = await self._register_and_login(client, "intended@example.com")
        accepted = await client.post("/v1/auth/accept-invite", headers=invitee, json={"token": token})
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["organization_id"] == org_and_tokens["org_id"]

    async def test_email_match_ignores_case_and_whitespace(self, client: AsyncClient, org_and_tokens) -> None:
        # Invites are stored lower-cased; the signed-in address may still differ in case.
        invited = await client.post(
            "/v1/orgs/current/members/invite",
            headers=org_headers(org_and_tokens),
            json={"email": "case.probe@example.com", "role_keys": ["member"]},
        )
        assert invited.status_code == 201, invited.text
        token = await _latest_invite_token("case.probe@example.com")
        joiner = await self._register_and_login(client, " Case.Probe@Example.com ")

        accepted = await client.post("/v1/auth/accept-invite", headers=joiner, json={"token": token})
        assert accepted.status_code == 200, accepted.text
