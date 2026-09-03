"""Typed errors mirroring the API's problem+json semantics."""

from __future__ import annotations

from typing import Any


class SynapseError(Exception):
    """Any non-2xx API response."""

    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self.status = status
        self.body = body
        super().__init__(str(body.get("detail") or body.get("title") or f"API error {status}"))


class SynapseAuthError(SynapseError):
    """401 — bad credentials (or revoked/expired key)."""


class SynapseNotFoundError(SynapseError):
    """404 — missing resource, or cross-tenant (indistinguishable by design)."""


class SynapseFeatureGatedError(SynapseError):
    """403 feature_not_entitled — carries available_in + upgrade_url."""

    @property
    def feature(self) -> str | None:
        return self.body.get("feature")

    @property
    def available_in(self) -> list[str]:
        return list(self.body.get("available_in") or [])


class SynapseLimitError(SynapseError):
    """402 — plan limit exceeded; carries metric + limit + upgrade_url."""

    @property
    def metric(self) -> str | None:
        return self.body.get("metric")

    @property
    def limit(self) -> int | None:
        return self.body.get("limit")


def error_for(status: int, body: dict[str, Any]) -> SynapseError:
    title = str(body.get("title", ""))
    if status == 401:
        return SynapseAuthError(status, body)
    if status == 404:
        return SynapseNotFoundError(status, body)
    if status == 402:
        return SynapseLimitError(status, body)
    if status == 403 and "feature" in body:
        return SynapseFeatureGatedError(status, body)
    return SynapseError(status, body)
