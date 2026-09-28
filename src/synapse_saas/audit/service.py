"""Audit service: one call, one immutable row, same transaction as the change."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from synapse_saas.audit.models import AuditLog
from synapse_saas.core import context
from synapse_saas.core.ids import uuid_v7


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def log(
        self,
        event_type: str,
        *,
        organization_id: UUID | None = None,
        actor_user_id: UUID | None = None,
        actor_type: str = "user",
        target_type: str | None = None,
        target_id: UUID | None = None,
        diff: dict[str, Any] | None = None,
    ) -> AuditLog:
        """Record an audit row in the caller's transaction.

        Actor resolution: an explicit `actor_user_id` wins; otherwise the bound
        principal. A programmatic principal (API key) is attributed to the human
        who created the key with `actor_type="api_key"` and the key id in the
        diff — its `user_id` is a sentinel that matches no `users` row and must
        never be written to the FK column.
        """
        user = context.current_user()
        effective_actor = actor_user_id
        effective_type = actor_type
        effective_diff = diff
        if effective_actor is None and user is not None:
            if user.api_key_id is not None:
                effective_actor = user.api_key_creator_id
                effective_type = "api_key"
                effective_diff = {**(diff or {}), "api_key_id": str(user.api_key_id)}
            else:
                effective_actor = user.user_id
        if effective_actor is None and effective_type == "user":
            effective_type = "system"
        request_id = context.current_request_id()

        entry = AuditLog(
            id=uuid_v7(),
            organization_id=organization_id,
            actor_user_id=effective_actor,
            actor_type=effective_type,
            event_type=event_type,
            target_type=target_type,
            target_id=target_id,
            diff=effective_diff,
            request_id=request_id,
        )
        self.session.add(entry)
        return entry
