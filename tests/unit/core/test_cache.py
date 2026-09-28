"""VersionedCache correctness (P3 / WS-D D5)."""

from __future__ import annotations

from typing import Any

import pytest

from synapse_saas.core import cache as cache_module
from synapse_saas.core.cache import (
    TTLDictBackend,
    VersionedCache,
    commit_and_flush_bumps,
    defer_bump,
    discard_deferred_bumps,
    flush_deferred_bumps,
)


@pytest.fixture(autouse=True)
def _isolated_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = TTLDictBackend()
    monkeypatch.setattr(cache_module, "_backend", lambda: backend)


class TestVersionAtRead:
    async def test_set_uses_the_version_seen_at_read(self) -> None:
        """A bump between read and write must leave the NEW version empty."""
        cache = VersionedCache("t")
        body, version = await cache.get_versioned("k")
        assert body is None and version == 0
        await cache.bump("k")  # a concurrent writer invalidated meanwhile
        await cache.set("k", "stale-body", version=version)
        assert await cache.get("k") is None  # the stale body sits under the old version only
        assert await cache.current_version("k") == 1

    async def test_set_without_version_reads_a_fresh_one(self) -> None:
        cache = VersionedCache("t")
        await cache.bump("k")
        await cache.set("k", "v1-body")
        assert await cache.get("k") == "v1-body"

    async def test_delete_is_a_bump_not_a_reset(self) -> None:
        cache = VersionedCache("t")
        await cache.set("k", "under-v0")
        await cache.bump("k")
        await cache.set("k", "under-v1")
        await cache.delete("k")
        # resetting to 0 would resurrect "under-v0"; a bump moves to v2 (empty)
        assert await cache.get("k") is None
        assert await cache.current_version("k") == 2

    async def test_scoped_bodies_miss_when_any_scope_bumps(self) -> None:
        cache = VersionedCache("flags")
        body, token = await cache.get_scoped("flag", "all", "org:o1", "user:u1")
        assert body is None
        await cache.set_scoped("flag", "1", token)
        assert (await cache.get_scoped("flag", "all", "org:o1", "user:u1"))[0] == "1"
        # a different scope set never sees this body, even at identical versions
        assert (await cache.get_scoped("flag", "all", "org:o1", "user:u2"))[0] is None
        await cache.bump("user:u1")
        assert (await cache.get_scoped("flag", "all", "org:o1", "user:u1"))[0] is None
        await cache.bump("all")
        assert (await cache.get_scoped("flag", "all", "org:o1", "user:u1"))[0] is None


class _FakeSession:
    def __init__(self) -> None:
        self.info: dict[str, Any] = {}
        self.committed = 0

    async def commit(self) -> None:
        self.committed += 1


class TestDeferredBumps:
    async def test_deferred_bump_runs_after_commit(self) -> None:
        cache = VersionedCache("t")
        session = _FakeSession()
        defer_bump(session, cache, "k")
        defer_bump(session, cache, "k")  # de-duplicated
        assert await cache.current_version("k") == 0  # nothing yet: the change is not durable
        await commit_and_flush_bumps(session)
        assert session.committed == 1
        assert await cache.current_version("k") == 1
        assert await flush_deferred_bumps(session) == 0  # queue drained

    async def test_discard_on_rollback(self) -> None:
        cache = VersionedCache("t")
        session = _FakeSession()
        defer_bump(session, cache, "k")
        discard_deferred_bumps(session)
        assert await flush_deferred_bumps(session) == 0
        assert await cache.current_version("k") == 0
