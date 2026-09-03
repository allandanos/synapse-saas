"""Stubs, redis factory, logging, notifier — small surface, quick tests."""

from __future__ import annotations

import pytest


class TestNoopNotifier:
    async def test_send_does_not_raise(self) -> None:
        from synapse_saas.notifications import NoopNotifier

        await NoopNotifier().send(to="a@b.example", subject="s", body="b")


class TestStorageInterface:
    async def test_module_importable(self) -> None:
        from synapse_saas.storage import get_storage

        assert callable(get_storage)


class TestFeatureFlagInterface:
    async def test_protocol_importable(self) -> None:
        from synapse_saas.feature_flags import FeatureFlagService

        assert FeatureFlagService is not None


class TestRedisFactory:
    def test_none_when_unconfigured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import synapse_saas.core.redis as redis_module

        monkeypatch.setattr(redis_module, "_client", None)
        monkeypatch.setenv("SYNAPSE_REDIS_URL", "")
        from synapse_saas.core.config import get_settings

        get_settings.cache_clear()
        assert redis_module.get_redis() is None
        get_settings.cache_clear()

    async def test_close_redis_is_safe(self) -> None:
        from synapse_saas.core.redis import close_redis

        await close_redis()  # no client ⇒ no-op, must not raise


class TestLoggingConfig:
    def test_configure_logging_dev(self, capsys: pytest.CaptureFixture[str]) -> None:
        from synapse_saas.core.logging import configure_logging, get_logger

        configure_logging()
        get_logger("test").info("hello-structured", key="value")
        captured = capsys.readouterr()
        assert "hello-structured" in captured.out + captured.err

    def test_bind_request_context_noop_without_values(self) -> None:
        from synapse_saas.core.logging import bind_request_context

        bind_request_context()  # no contextvars set ⇒ must not raise


class TestPaginationModels:
    def test_page_build(self) -> None:
        from synapse_saas.core.pagination import Page

        page = Page[int].build([1, 2, 3], total=10, limit=3, offset=0)
        assert page.data == [1, 2, 3]
        assert page.meta.total == 10
        assert page.meta.limit == 3
        assert page.meta.offset == 0

    def test_page_params_bounds(self) -> None:
        from pydantic import ValidationError

        from synapse_saas.core.pagination import PageParams

        assert PageParams().limit == 50
        with pytest.raises(ValidationError):
            PageParams(limit=101)


class TestEntrypoints:
    def test_module_importable(self) -> None:
        from synapse_saas import apps_entrypoints

        assert callable(apps_entrypoints.run_api)
        assert callable(apps_entrypoints.run_worker)
