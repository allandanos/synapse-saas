"""API key model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from synapse_saas.core.db import Base, TenantMixin, TimestampMixin


class ApiKey(Base, TenantMixin, TimestampMixin):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # First characters of the plaintext, e.g. "sk_ab12cd" — for display only
    prefix: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)
    # SHA-256 of the full plaintext key
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    # Permission keys the key may exercise; empty ⇒ everything the creator could
    scopes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, nullable=False, server_default=text("'{}'")
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    metadata_jsonb: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    @property
    def is_active(self) -> bool:
        from datetime import UTC

        now = datetime.now(UTC)
        if self.revoked_at is not None:
            return False
        return self.expires_at is None or now < self.expires_at
