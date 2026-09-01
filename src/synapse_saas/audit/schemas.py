"""Audit API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID | None
    actor_user_id: uuid.UUID | None
    actor_type: str
    event_type: str
    target_type: str | None
    target_id: uuid.UUID | None
    diff: dict[str, Any] | None
    request_id: str | None
    created_at: datetime


class AuditPage(BaseModel):
    data: list[AuditEntryRead]
    next_cursor: str | None = None
