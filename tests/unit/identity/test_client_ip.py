"""Rate-limit client identification: X-Forwarded-For is only trusted from trusted proxies."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from synapse_saas.core.config import get_settings
from synapse_saas.identity.rate_limit import _client_ip


def _request(peer: str, xff: str | None = None) -> SimpleNamespace:
    headers = {"x-forwarded-for": xff} if xff is not None else {}
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers=headers)


@pytest.fixture(autouse=True)
def _reset_settings():  # type: ignore[no-untyped-def]
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestNoTrustedProxies:
    def test_header_is_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SYNAPSE_TRUSTED_PROXIES", raising=False)
        # An attacker rotating X-Forwarded-For must still be bucketed by the socket peer
        assert _client_ip(_request("203.0.113.9", "1.1.1.1")) == "203.0.113.9"  # type: ignore[arg-type]

    def test_missing_client_is_unknown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SYNAPSE_TRUSTED_PROXIES", raising=False)
        req = SimpleNamespace(client=None, headers={"x-forwarded-for": "1.1.1.1"})
        assert _client_ip(req) == "unknown"  # type: ignore[arg-type]


class TestTrustedProxies:
    def test_rightmost_untrusted_hop_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SYNAPSE_TRUSTED_PROXIES", "10.0.0.0/8,192.168.0.0/16")
        # client → proxyA(10.0.0.5) → proxyB(10.0.0.6) → us; each proxy appends its peer
        req = _request("10.0.0.6", "198.51.100.7, 10.0.0.5")
        assert _client_ip(req) == "198.51.100.7"  # type: ignore[arg-type]

    def test_client_spoofed_prefix_is_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SYNAPSE_TRUSTED_PROXIES", "10.0.0.0/8")
        # The attacker sent "X-Forwarded-For: 1.1.1.1"; the proxy appended the real peer
        req = _request("10.0.0.6", "1.1.1.1, 198.51.100.7")
        assert _client_ip(req) == "198.51.100.7"  # type: ignore[arg-type]

    def test_untrusted_peer_ignores_header(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SYNAPSE_TRUSTED_PROXIES", "10.0.0.0/8")
        req = _request("203.0.113.9", "1.1.1.1")
        assert _client_ip(req) == "203.0.113.9"  # type: ignore[arg-type]

    def test_all_hops_trusted_falls_back_to_peer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SYNAPSE_TRUSTED_PROXIES", "10.0.0.0/8")
        req = _request("10.0.0.6", "10.0.0.5")
        assert _client_ip(req) == "10.0.0.6"  # type: ignore[arg-type]

    def test_garbage_hops_are_not_trusted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SYNAPSE_TRUSTED_PROXIES", "10.0.0.0/8")
        req = _request("10.0.0.6", "not-an-ip, 10.0.0.5")
        assert _client_ip(req) == "not-an-ip"  # type: ignore[arg-type]


class TestSettingsParsing:
    def test_csv_and_json_lists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SYNAPSE_TRUSTED_PROXIES", "10.0.0.0/8, 172.16.0.0/12")
        assert get_settings().trusted_proxies == ["10.0.0.0/8", "172.16.0.0/12"]
        get_settings.cache_clear()
        monkeypatch.setenv("SYNAPSE_TRUSTED_PROXIES", '["10.0.0.0/8"]')
        assert get_settings().trusted_proxies == ["10.0.0.0/8"]

    def test_invalid_cidr_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SYNAPSE_TRUSTED_PROXIES", "not-a-cidr")
        with pytest.raises(Exception, match="not-a-cidr"):
            get_settings()
