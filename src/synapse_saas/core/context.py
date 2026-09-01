"""Request-scoped tenant and user context.

The single source of truth for "who is acting, in which org" — every layer below the
router reads these contextvars instead of threading parameters.

⚠ Contextvars are copied at task creation and do NOT propagate into fire-and-forget
tasks or worker jobs. Any background work must carry `organization_id`/`user_id`
explicitly in its payload and re-establish context at job start. This behavior is
pinned by tests/unit/core/test_context.py.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from types import TracebackType
from typing import Self
from uuid import UUID

from synapse_saas.core.errors import TenantContextMissingError


@dataclass(frozen=True, slots=True)
class TenantContext:
    """The organization a request/job is scoped to."""

    organization_id: UUID
    slug: str
    is_platform: bool = False  # platform-admin / system-job scope (no tenant filtering)


@dataclass(frozen=True, slots=True)
class UserContext:
    """The authenticated actor."""

    user_id: UUID
    email: str
    is_platform_admin: bool = False
    permission_keys: frozenset[str] = field(default_factory=frozenset)


_tenant: ContextVar[TenantContext | None] = ContextVar("synapse_tenant", default=None)
_user: ContextVar[UserContext | None] = ContextVar("synapse_user", default=None)
_request_id: ContextVar[str | None] = ContextVar("synapse_request_id", default=None)


# ── Tenant ─────────────────────────────────────────────────────────────────────


def set_tenant(ctx: TenantContext) -> Token[TenantContext | None]:
    return _tenant.set(ctx)


def current_tenant() -> TenantContext | None:
    return _tenant.get()


def require_tenant() -> TenantContext:
    ctx = _tenant.get()
    if ctx is None:
        raise TenantContextMissingError("No tenant context is active for this operation")
    return ctx


def reset_tenant(token: Token[TenantContext | None]) -> None:
    _tenant.reset(token)


# ── User ───────────────────────────────────────────────────────────────────────


def set_user(ctx: UserContext) -> Token[UserContext | None]:
    return _user.set(ctx)


def current_user() -> UserContext | None:
    return _user.get()


def require_user() -> UserContext:
    ctx = _user.get()
    if ctx is None:
        raise TenantContextMissingError("No user context is active for this operation")
    return ctx


def reset_user(token: Token[UserContext | None]) -> None:
    _user.reset(token)


# ── Request id ─────────────────────────────────────────────────────────────────


def set_request_id(request_id: str) -> Token[str | None]:
    return _request_id.set(request_id)


def current_request_id() -> str | None:
    return _request_id.get()


def reset_request_id(token: Token[str | None]) -> None:
    _request_id.reset(token)


@dataclass(slots=True)
class TenantScope:
    """Context manager that scopes a block (or background task body) to a tenant."""

    ctx: TenantContext
    _token: Token[TenantContext | None] | None = None

    def __enter__(self) -> Self:
        self._token = set_tenant(self.ctx)
        return self

    def __exit__(self, *exc: object) -> None:
        reset_tenant(self._token)

    async def __aenter__(self) -> Self:
        return self.__enter__()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.__exit__(exc_type, exc, tb)
