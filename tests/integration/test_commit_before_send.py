"""CommitBeforeSendMiddleware really commits BEFORE the first response byte
(P4 / WS-F F5), and the app refuses to boot if that guarantee silently
disappears with a FastAPI upgrade."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.pg


class TestOrdering:
    async def test_commit_happens_before_response_start(
        self, client: AsyncClient, app, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Observe the real interleaving: session.commit() must precede http.response.start."""
        from sqlalchemy.ext.asyncio import AsyncSession

        from synapse_saas.core.commit_before_send import CommitBeforeSendMiddleware

        events: list[str] = []
        original_commit = AsyncSession.commit

        async def recording_commit(self: Any) -> None:
            events.append("commit")
            await original_commit(self)

        monkeypatch.setattr(AsyncSession, "commit", recording_commit)

        original_call = CommitBeforeSendMiddleware.__call__

        async def recording_call(self: Any, scope: Any, receive: Any, send: Any) -> None:
            async def recording_send(message: Any) -> None:
                if message["type"] == "http.response.start":
                    events.append("response.start")
                await send(message)

            await original_call(self, scope, receive, recording_send)

        monkeypatch.setattr(CommitBeforeSendMiddleware, "__call__", recording_call)

        res = await client.post(
            "/v1/auth/register",
            json={"email": "order@example.com", "password": "password12345", "display_name": "O"},
        )
        assert res.status_code == 201, res.text
        assert "commit" in events and "response.start" in events
        assert events.index("commit") < events.index("response.start"), events

    async def test_write_is_visible_to_the_very_next_request(self, client: AsyncClient) -> None:
        """The symptom this middleware exists for: register → immediately use the token."""
        reg = await client.post(
            "/v1/auth/register",
            json={"email": "fast@example.com", "password": "password12345", "display_name": "F"},
        )
        token = reg.json()["tokens"]["access_token"]
        me = await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200, me.text


class TestStartupSelfTest:
    async def test_boot_refused_when_the_private_scope_key_vanishes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastapi import FastAPI

        from synapse_saas.core import commit_before_send as cbs

        app = FastAPI()
        app.add_middleware(cbs.CommitBeforeSendMiddleware)

        @app.get("/healthz")
        async def healthz() -> dict[str, str]:
            return {"status": "ok"}

        await cbs.assert_effective(app)  # the key exists on this FastAPI: passes

        monkeypatch.setattr(cbs, "STACK_SCOPE_KEY", "fastapi_renamed_this_key")
        with pytest.raises(cbs.CommitBeforeSendIneffectiveError, match="would be a no-op"):
            await cbs.assert_effective(app)
