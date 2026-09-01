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
        """Record an audit row. Never raises — audit must not block the mutation."""
        user = context.current_user()
        effective_actor = actor_user_id or (user.user_id if user else None)
        request_id = context.current_request_id()

        entry = AuditLog(
            id=uuid_v7(),
            organization_id=organization_id,
            actor_user_id=effective_actor,
            actor_type=actor_type if effective_actor is not None else "system",
            event_type=event_type,
            target_type=target_type,
            target_id=target_id,
            diff=diff,
            request_id=request_id,
        )
        self.session.add(entry)
        return entry
