"""Auth dependencies: bearer-token → principal (user JWT or API key).

Two credential types share one code path:
- JWT access token → the User row it names
- `sk_…` API key  → a synthetic principal bound to the key's organization

Downstream code sees `CurrentUser` and stays credential-agnostic; permission
checks consult key scopes when the principal is a key (see authorization).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from synapse_saas.core import context
from synapse_saas.core.context import UserContext
from synapse_saas.core.db import get_session
from synapse_saas.core.errors import AuthenticationError
from synapse_saas.core.logging import get_logger
from synapse_saas.core.security import decode_access_token
from synapse_saas.identity.models import User

logger = get_logger(__name__)

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated actor, credential-agnostic.

    `user` is set for JWT auth; `api_key_id` is set for key auth. Exactly one.
    """

    user: User | None = None
    api_key_id: uuid.UUID | None = None

    @property
    def is_api_key(self) -> bool:
        return self.api_key_id is not None

    @property
    def id(self) -> uuid.UUID:
        """The acting identity's id (user id or key id)."""
        if self.user is not None:
            return self.user.id
        assert self.api_key_id is not None
        return self.api_key_id

    @property
    def email(self) -> str:
        if self.user is not None:
            return str(self.user.email)
        return "apikey"


async def get_current_user(request: Request, session: SessionDep) -> User:
    """Bearer → User: JWT names a real user; `sk_` key synthesizes a principal.

    Key auth binds TenantContext (the key's org) and UserContext (the key's
    scopes) right here, so every downstream dependency — tenant resolution,
    permission checks — works unchanged for both credential types.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise AuthenticationError("Missing bearer token")

    token = auth.removeprefix("Bearer ")

    # ── API key path ────────────────────────────────────────────────────────
    if token.startswith("sk_"):
        from synapse_saas.api_keys.dependencies import bind_api_key_context
        from synapse_saas.api_keys.service import ApiKeyService
        from synapse_saas.tenancy.models import Organization

        key = await ApiKeyService(session).verify(token)
        if key is None:
            _inc_key_auth("invalid")
            raise AuthenticationError("Invalid API key")
        _inc_key_auth("ok")
        org = await session.get(Organization, key.organization_id)
        if org is None or org.deleted_at is not None or org.status != "active":
            raise AuthenticationError("Invalid API key")
        bind_api_key_context(key, org)
        from synapse_saas.api_keys.dependencies import meter_api_key_request

        await meter_api_key_request(session, key.organization_id)

        # Transient (unpersisted) stand-in so typed routers work unchanged.
        # require_permission short-circuits on api_key_scopes, so this user's
        # id is never consulted for RBAC.
        return User(
            id=uuid.uuid4(),
            email=f"apikey:{key.prefix}",
            display_name=f"API key {key.name}",
            is_active=True,
            is_platform_admin=False,
        )

    # ── JWT path ─────────────────────────────────────────────────────────────
    payload = decode_access_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise AuthenticationError("Invalid token subject")

    try:
        parsed_id = uuid.UUID(str(user_id))
    except ValueError as exc:
        raise AuthenticationError("Invalid token subject") from exc

    user = await session.get(User, parsed_id)
    if user is None or not user.is_active:
        raise AuthenticationError("User not found or inactive")

    # Bind user context for services/audit on this request
    context.set_user(
        UserContext(
            user_id=user.id,
            email=str(user.email),
            is_platform_admin=user.is_platform_admin,
        )
    )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_principal(request: Request, session: SessionDep) -> Principal:
    """Resolve either credential type into a Principal.

    Order: `sk_` prefix ⇒ API key; anything else ⇒ JWT. Key auth additionally
    binds TenantContext to the key's org so org-scoped routes just work.
    """
    from synapse_saas.api_keys.dependencies import bind_api_key_context, try_api_key_auth
    from synapse_saas.tenancy.models import Organization

    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ") and auth.removeprefix("Bearer ").startswith("sk_"):
        key = await try_api_key_auth(request, session)
        if key is None:
            raise AuthenticationError("Invalid API key")
        org = await session.get(Organization, key.organization_id)
        if org is None or org.deleted_at is not None or org.status != "active":
            raise AuthenticationError("Invalid API key")
        bind_api_key_context(key, org)
        return Principal(api_key_id=key.id)

    user = await get_current_user(request, session)
    return Principal(user=user)


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def _inc_key_auth(outcome: str) -> None:
    try:
        from synapse_saas.core import metrics

        metrics.API_KEY_AUTH.labels(outcome=outcome).inc()
    except Exception as exc:  # metrics must never fail auth
        logger.debug("metrics_inc_failed", metric="api_key_auth", error=str(exc))
