"""Auth dependencies: bearer-token → UserContext."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from synapse_saas.core import context
from synapse_saas.core.context import UserContext
from synapse_saas.core.db import get_session
from synapse_saas.core.errors import AuthenticationError
from synapse_saas.core.security import decode_access_token
from synapse_saas.identity.models import User

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(request: Request, session: SessionDep) -> User:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise AuthenticationError("Missing bearer token")

    payload = decode_access_token(auth.removeprefix("Bearer "))
    user_id = payload.get("sub")
    if not user_id:
        raise AuthenticationError("Invalid token subject")

    import uuid

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
