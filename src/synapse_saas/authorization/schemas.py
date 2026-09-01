"""Authorization API schemas."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PermissionRead(BaseModel):
    key: str
    resource: str
    action: str
    description: str | None


class RoleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    name: str
    description: str | None
    is_system: bool
    permissions: list[str] = []

    @field_validator("permissions", mode="before")
    @classmethod
    def _project_permissions(cls, v: object) -> object:
        """roles.permissions holds Permission ORM rows; project to key strings."""
        if isinstance(v, (list, tuple)):
            return [p.key if hasattr(p, "key") else str(p) for p in v]
        return v


class RoleCreate(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9_]+$", min_length=2, max_length=64)
    name: str = Field(min_length=2, max_length=200)
    description: str | None = None
    permissions: list[str]


class RoleUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=200)
    description: str | None = None
    permissions: list[str] | None = None
