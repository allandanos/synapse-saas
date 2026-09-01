"""Transactional outbox writer.

`append_outbox` is called INSIDE the mutating transaction — the event commits
atomically with the state change or not at all. The arq worker later drains
`outbox_events` to fan out webhook deliveries and invoke in-process handlers.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from synapse_saas.core import events
from synapse_saas.core.ids import uuid_v7


def append_outbox(
    session: AsyncSession,
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: UUID | str,
    payload: dict[str, Any],
    organization_id: UUID | None = None,
) -> None:
    """Queue a domain event in the same transaction as the state change."""
    from synapse_saas.audit.models import OutboxEvent  # local: avoids model import cycle at module load

    session.add(
        OutboxEvent(
            id=uuid_v7(),
            aggregate_type=aggregate_type,
            aggregate_id=UUID(str(aggregate_id)),
            organization_id=organization_id,
            event_type=event_type,
            payload=payload,
        )
    )


__all__ = ["append_outbox", "events"]
