"""Feature flag API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FlagCreate(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9_.-]+$", min_length=2, max_length=100)
    name: str = Field(min_length=2, max_length=200)
    description: str | None = None
    enabled: bool = False
    rollout_percentage: int | None = Field(None, ge=0, le=100)


class FlagUpdate(BaseModel):
    enabled: bool | None = None
    rollout_percentage: int | None = Field(None, ge=0, le=100)


class FlagRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    name: str
    description: str | None
    enabled: bool
    rollout_percentage: int | None
    created_at: datetime


class OverrideCreate(BaseModel):
    organization_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    enabled: bool
    note: str | None = None

    @model_validator(mode="after")
    def _require_scope(self) -> OverrideCreate:
        if self.organization_id is None and self.user_id is None:
            raise ValueError("override requires organization_id or user_id")
        return self


class OverrideRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    flag_key: str
    organization_id: uuid.UUID | None
    user_id: uuid.UUID | None
    enabled: bool
    note: str | None
    created_at: datetime


class FlagCheck(BaseModel):
    key: str
    enabled: bool
