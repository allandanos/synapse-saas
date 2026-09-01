"""Unit tests for tenant/user context propagation.

Pins the async rule: contextvars do NOT propagate into `create_task` bodies set after
task creation, and DO propagate into tasks created after the context was set. Background
jobs must therefore carry org ids explicitly.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from synapse_saas.core import context
from synapse_saas.core.context import TenantContext, TenantScope, UserContext, require_tenant


def make_tenant() -> TenantContext:
    return TenantContext(organization_id=uuid4(), slug="acme")


class TestSyncContext:
    def test_set_and_read(self) -> None:
        ctx = make_tenant()
        token = context.set_tenant(ctx)
        assert context.current_tenant() is ctx
        context.reset_tenant(token)
        assert context.current_tenant() is None

    def test_require_tenant_raises_when_missing(self) -> None:
        with pytest.raises(Exception, match="tenant context"):
            require_tenant()

    def test_user_round_trip(self) -> None:
        user = UserContext(user_id=uuid4(), email="a@b.c", permission_keys=frozenset({"member:read"}))
        token = context.set_user(user)
        assert context.require_user().permission_keys == frozenset({"member:read"})
        context.reset_user(token)

    def test_nested_scopes_restore(self) -> None:
        outer = make_tenant()
        inner = make_tenant()
        with TenantScope(outer):
            with TenantScope(inner):
                assert context.current_tenant() is inner
            assert context.current_tenant() is outer
        assert context.current_tenant() is None

    @pytest.mark.asyncio
    async def test_async_context_manager(self) -> None:
        ctx = make_tenant()
        async with TenantScope(ctx):
            assert context.current_tenant() is ctx
        assert context.current_tenant() is None


class TestAsyncPropagation:
    async def test_context_visible_in_awaited_coroutine(self) -> None:
        ctx = make_tenant()
        with TenantScope(ctx):
            seen = context.current_tenant()
        assert seen is ctx

    async def test_context_copied_into_create_task(self) -> None:
        # Tasks snapshot contextvars at creation time — set BEFORE create_task works.
        ctx = make_tenant()
        with TenantScope(ctx):
            task = asyncio.create_task(_read_tenant())
            assert await task is ctx

    async def test_context_not_retroactive_into_running_task(self) -> None:
        # A task created BEFORE the context is set must not see it — this is the
        # documented rule that forces worker jobs to carry org ids explicitly.
        task = asyncio.create_task(_read_tenant_later())
        await asyncio.sleep(0.01)
        ctx = make_tenant()
        with TenantScope(ctx):
            await asyncio.sleep(0.01)
            seen = await task
        assert seen is None

    async def test_gather_isolation(self) -> None:
        # Two concurrent tasks each set their own tenant; no cross-contamination.
        ctx_a, ctx_b = make_tenant(), make_tenant()
        results = await asyncio.gather(
            _set_and_read(ctx_a),
            _set_and_read(ctx_b),
        )
        assert results == [ctx_a, ctx_b]
        assert context.current_tenant() is None


async def _read_tenant() -> TenantContext | None:
    return context.current_tenant()


async def _read_tenant_later() -> TenantContext | None:
    await asyncio.sleep(0.05)
    return context.current_tenant()


async def _set_and_read(ctx: TenantContext) -> TenantContext:
    with TenantScope(ctx):
        await asyncio.sleep(0.01)
        return context.current_tenant()
