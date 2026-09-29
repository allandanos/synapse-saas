"""Defects the conformance suite surfaced while freezing contract v1 (P6 / WS-K).

Each test pins the corrected behaviour so the reference implementation and the
ports (ADR 0012) agree on it.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from synapse_saas.testing.fixtures import org_headers, platform_admin_headers

pytestmark = pytest.mark.pg


class TestValidationProblems:
    async def test_request_parsing_failures_are_problem_documents(self, client: AsyncClient) -> None:
        res = await client.post("/v1/auth/register", json={"email": "nope", "password": "x"})
        assert res.status_code == 422
        doc = res.json()
        assert doc["type"].endswith("/validation_failed") and doc["title"] == "validation failed"
        assert doc["status"] == 422 and doc["request_id"] and doc["instance"] == "/v1/auth/register"
        assert doc["detail"].startswith("Invalid request: email")
        locs = {tuple(e["loc"]) for e in doc["errors"]}
        assert ("body", "email") in locs and ("body", "display_name") in locs

    async def test_query_validation_too(self, client: AsyncClient, org_and_tokens) -> None:
        res = await client.get("/v1/plans", headers=org_headers(org_and_tokens), params={"limit": 0})
        assert res.status_code == 422 and res.json()["title"] == "validation failed"
        assert res.json()["errors"][0]["loc"] == ["query", "limit"]


class TestSuspensionAppliesToEveryPrincipal:
    async def test_jwt_members_are_locked_out_while_suspended(
        self, client: AsyncClient, org_and_tokens
    ) -> None:
        admin = await platform_admin_headers(client)
        org_id = org_and_tokens["org_id"]
        assert (await client.post(f"/v1/orgs/{org_id}/suspend", headers=admin)).status_code == 204

        res = await client.get("/v1/orgs/current", headers=org_headers(org_and_tokens))
        assert res.status_code == 403, res.text
        assert res.json()["title"] == "organization suspended"
        assert res.json()["organization_id"] == org_id and res.json()["organization_status"] == "suspended"
        assert res.json()["status"] == 403  # extras never shadow the RFC 7807 members

        # Writes too — the whole tenant surface is closed, not just the profile
        blocked = await client.post(
            "/v1/api-keys", headers=org_headers(org_and_tokens), json={"name": "while-suspended"}
        )
        assert blocked.status_code == 403

        assert (await client.delete(f"/v1/orgs/{org_id}/suspend", headers=admin)).status_code == 204
        assert (await client.get("/v1/orgs/current", headers=org_headers(org_and_tokens))).status_code == 200

    async def test_non_members_still_get_404_not_403(self, client: AsyncClient, org_and_tokens) -> None:
        """Suspension must not become an existence oracle."""
        admin = await platform_admin_headers(client)
        org_id = org_and_tokens["org_id"]
        assert (await client.post(f"/v1/orgs/{org_id}/suspend", headers=admin)).status_code == 204
        reg = await client.post(
            "/v1/auth/register",
            json={"email": "stranger@example.com", "password": "password12345", "display_name": "S"},
        )
        stranger = {"Authorization": f"Bearer {reg.json()['tokens']['access_token']}", "X-Org-Id": org_id}
        assert (await client.get("/v1/orgs/current", headers=stranger)).status_code == 404


class TestRoleUpdateReturnsTheNewSet:
    async def test_patch_permissions_replaces_and_reflects(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        created = await client.post(
            "/v1/roles",
            headers=headers,
            json={"key": "auditor", "name": "Auditor", "permissions": ["audit:read", "org:read"]},
        )
        assert created.status_code == 201, created.text
        patched = await client.patch(
            f"/v1/roles/{created.json()['id']}", headers=headers, json={"permissions": ["org:read"]}
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["permissions"] == ["org:read"]
        listed = await client.get("/v1/roles", headers=headers)
        assert next(r for r in listed.json() if r["key"] == "auditor")["permissions"] == ["org:read"]


class TestPresignDownloadOnLocalDisk:
    async def test_answers_409_presign_unsupported(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        up = await client.post("/v1/files", headers=headers, files={"file": ("a.txt", b"x", "text/plain")})
        assert up.status_code == 201, up.text
        res = await client.post(f"/v1/files/{up.json()['id']}/presign", headers=headers)
        assert res.status_code == 409 and res.json()["title"] == "presign unsupported"


class TestPortFindings:
    """Defects the Node port surfaced while implementing milestone 2 against the reference."""

    async def test_ip_literal_host_is_not_a_tenant_slug(self, client: AsyncClient, org_and_tokens) -> None:
        switched = await client.post(
            "/v1/auth/switch-org",
            headers={"Authorization": f"Bearer {org_and_tokens['access_token']}"},
            json={"organization_id": org_and_tokens["org_id"]},
        )
        assert switched.status_code == 200, switched.text
        scoped = {"Authorization": f"Bearer {switched.json()['access_token']}", "Host": "127.0.0.1:8000"}
        res = await client.get("/v1/orgs/current", headers=scoped)  # no X-Org-Id: claim must win over "127"
        assert res.status_code == 200, res.text

    async def test_invite_email_event_names_the_org(self, client: AsyncClient, org_and_tokens) -> None:
        from sqlalchemy import select

        from synapse_saas.audit.models import OutboxEvent
        from synapse_saas.testing.fixtures import owner_session_factory

        res = await client.post(
            "/v1/orgs/current/members/invite",
            headers=org_headers(org_and_tokens),
            json={"email": "named@example.com", "role_keys": ["developer"]},
        )
        assert res.status_code == 201 and res.json()["role_keys"] == ["developer"], res.text
        async with owner_session_factory()() as session:
            rows = (
                (
                    await session.execute(
                        select(OutboxEvent).where(OutboxEvent.event_type == "member.invite_email")
                    )
                )
                .scalars()
                .all()
            )
        assert rows and rows[-1].payload["org_name"] == "Test Org"

    async def test_duplicate_invite_and_role_key_are_409(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        body = {"email": "twice@example.com", "role_keys": ["member"]}
        assert (
            await client.post("/v1/orgs/current/members/invite", headers=headers, json=body)
        ).status_code == 201
        again = await client.post("/v1/orgs/current/members/invite", headers=headers, json=body)
        assert again.status_code == 409 and again.json()["membership_status"] == "invited", again.text

        role = {"key": "dup_role", "name": "Dup", "permissions": ["org:read"]}
        assert (await client.post("/v1/roles", headers=headers, json=role)).status_code == 201
        dup = await client.post("/v1/roles", headers=headers, json=role)
        assert dup.status_code == 409 and dup.json()["key"] == "dup_role", dup.text

    async def test_framework_http_errors_are_problems(self, client: AsyncClient) -> None:
        missing = await client.get("/v1/nope")
        assert (
            missing.status_code == 404
            and missing.json()["title"] == "not found"
            and missing.json()["request_id"]
        )
        wrong = await client.delete("/v1/meta")
        assert wrong.status_code == 405 and wrong.json()["title"] == "method not allowed"


class TestJavaPortFindings:
    """Defect the Java port surfaced: deleting a custom role left holders' permissions stale."""

    async def test_deleting_a_role_recomputes_holders_permissions(
        self, client: AsyncClient, org_and_tokens
    ) -> None:
        from sqlalchemy import text

        from synapse_saas.testing.fixtures import owner_session_factory

        owner = org_headers(org_and_tokens)
        role = await client.post(
            "/v1/roles",
            headers=owner,
            json={"key": "auditor", "name": "Auditor", "permissions": ["audit:read"]},
        )
        assert role.status_code == 201, role.text

        reg = await client.post(
            "/v1/auth/register",
            json={"email": "holder@example.com", "password": "password12345", "display_name": "H"},
        )
        assert reg.status_code == 201
        invited = await client.post(
            "/v1/orgs/current/members/invite",
            headers=owner,
            json={"email": "holder@example.com", "role_keys": ["auditor"]},
        )
        assert invited.status_code == 201, invited.text
        async with owner_session_factory()() as session:
            token = (
                await session.execute(
                    text(
                        "SELECT payload->>'invite_token' FROM outbox_events "
                        "WHERE event_type = 'member.invite_email' ORDER BY created_at DESC LIMIT 1"
                    )
                )
            ).scalar_one()
        holder = {"Authorization": f"Bearer {reg.json()['tokens']['access_token']}"}
        accepted = await client.post("/v1/auth/accept-invite", headers=holder, json={"token": token})
        assert accepted.status_code == 200, accepted.text
        holder_in_org = {**holder, "X-Org-Id": org_and_tokens["org_id"]}
        assert (await client.get("/v1/audit", headers=holder_in_org)).status_code == 200

        assert (await client.delete(f"/v1/roles/{role.json()['id']}", headers=owner)).status_code == 204

        denied = await client.get("/v1/audit", headers=holder_in_org)
        assert denied.status_code == 403, denied.text  # the very next request sees the smaller set
        members = await client.get("/v1/orgs/current/members", headers=owner)
        holder_row = next(m for m in members.json()["data"] if m["email"] == "holder@example.com")
        assert holder_row["role_keys"] == []

    async def test_impossible_month_is_422_not_500(self, client: AsyncClient, org_and_tokens) -> None:
        """`2026-13` used to pass the YYYY-MM pattern and crash in strptime."""
        headers = org_headers(org_and_tokens)
        res = await client.get("/v1/usage/summary", headers=headers, params={"period": "2026-13"})
        assert res.status_code == 422 and res.json()["title"] == "validation failed", res.text
        draft = await client.post("/v1/billing/invoices/draft", headers=headers, json={"period": "2026-00"})
        assert draft.status_code == 422, draft.text
        assert (
            await client.get("/v1/usage/summary", headers=headers, params={"period": "2026-12"})
        ).status_code == 200


class TestNodePortMilestone4Findings:
    async def test_finalize_is_idempotent(self, client: AsyncClient, org_and_tokens) -> None:
        """A second finalize used to re-number the invoice and bump issued_at."""
        headers = org_headers(org_and_tokens)
        draft = await client.post("/v1/billing/invoices/draft", headers=headers, json={})
        assert draft.status_code == 201, draft.text
        invoice_id = draft.json()["id"]
        first = await client.post(f"/v1/billing/invoices/{invoice_id}/finalize", headers=headers)
        assert first.status_code == 200 and first.json()["number"], first.text
        second = await client.post(f"/v1/billing/invoices/{invoice_id}/finalize", headers=headers)
        assert second.status_code == 200, second.text
        assert second.json()["number"] == first.json()["number"]
        assert second.json()["issued_at"] == first.json()["issued_at"]
        listed = await client.get("/v1/billing/invoices", headers=headers)
        assert [i["number"] for i in listed.json()] == [first.json()["number"]]


class TestJavaPortMilestone4Findings:
    async def test_invoice_email_falls_back_to_the_owner(
        self, client: AsyncClient, org_and_tokens, monkeypatch
    ) -> None:
        """Framework-drafted invoices have no billing customer; the mail used to be dropped
        unless settings.billing_email was set, while every other billing email fell back
        to the owner."""
        from synapse_saas.notifications import handlers

        sent: list[dict] = []

        class RecordingNotifier:
            async def send(self, *, to, subject, body, attachments=None):
                sent.append({"to": to, "subject": subject, "attachments": list(attachments or [])})

        monkeypatch.setattr(handlers, "get_notifier", RecordingNotifier)
        headers = org_headers(org_and_tokens)
        draft = await client.post("/v1/billing/invoices/draft", headers=headers, json={})
        assert draft.status_code == 201, draft.text
        finalized = await client.post(f"/v1/billing/invoices/{draft.json()['id']}/finalize", headers=headers)
        assert finalized.status_code == 200, finalized.text

        await handlers.handle_event(
            "invoice.email", {"invoice_id": draft.json()["id"], "reason": "finalized"}
        )
        assert len(sent) == 1, sent
        assert sent[0]["to"] == "owner@example.com"  # the fixture's org owner
        assert sent[0]["attachments"][0].filename.endswith(".pdf")


class TestNodePortMilestone5Findings:
    async def test_file_and_endpoint_events_reach_the_outbox(
        self, client: AsyncClient, org_and_tokens
    ) -> None:
        """events.json advertised file.* and webhook.endpoint_* but nothing emitted them."""
        from sqlalchemy import select

        from synapse_saas.audit.models import OutboxEvent
        from synapse_saas.testing.fixtures import owner_session_factory

        headers = org_headers(org_and_tokens)
        up = await client.post("/v1/files", headers=headers, files={"file": ("e.txt", b"ev", "text/plain")})
        assert up.status_code == 201, up.text
        assert (await client.delete(f"/v1/files/{up.json()['id']}", headers=headers)).status_code == 204
        ep = await client.post(
            "/v1/webhooks/endpoints",
            headers=headers,
            json={"url": "https://hooks.example.com/x", "events": []},
        )
        assert ep.status_code == 201, ep.text
        assert (
            await client.delete(f"/v1/webhooks/endpoints/{ep.json()['id']}", headers=headers)
        ).status_code == 204

        async with owner_session_factory()() as session:
            rows = (
                await session.execute(
                    select(OutboxEvent.event_type, OutboxEvent.audience, OutboxEvent.payload)
                )
            ).all()
        types = {r.event_type for r in rows}
        assert {
            "file.uploaded",
            "file.deleted",
            "webhook.endpoint_created",
            "webhook.endpoint_deleted",
        } <= types
        assert all(
            r.audience == "public" for r in rows if r.event_type.startswith(("file.", "webhook.endpoint"))
        )
        assert all("secret" not in r.payload for r in rows if r.event_type.startswith("webhook.endpoint"))

    async def test_endpoint_pages_never_overlap(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        for i in range(5):
            res = await client.post(
                "/v1/webhooks/endpoints",
                headers=headers,
                json={"url": f"https://hooks.example.com/{i}", "events": []},
            )
            assert res.status_code == 201
        seen: list[str] = []
        for offset in (0, 2, 4):
            page = await client.get(
                "/v1/webhooks/endpoints", headers=headers, params={"limit": 2, "offset": offset}
            )
            seen.extend(e["id"] for e in page.json())
        assert len(seen) == 5 and len(set(seen)) == 5
