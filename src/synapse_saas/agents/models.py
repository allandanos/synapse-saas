"""Agent registry models.

Governance and billing only — see ADR 0007. This framework registers agents,
gates them behind entitlements, meters their usage, and bills for it; it does
not execute them. `config` is opaque JSON owned by whichever runtime executes
the agent (model, system-prompt refs, tool allowlists).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from synapse_saas.core.db import Base, TimestampMixin

AGENT_STATUSES = frozenset({"active", "disabled"})


class Agent(Base, TimestampMixin):
    """An org-scoped registered agent — the CRM row, not the runner."""

    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_agents_org_slug"),
        CheckConstraint("status IN ('active', 'disabled')", name="ck_agents_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def is_active(self) -> bool:
        return self.status == "active" and self.deleted_at is None


def utcnow() -> datetime:
    return datetime.now(UTC)
