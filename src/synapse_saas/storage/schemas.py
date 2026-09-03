"""Storage API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class FileUploadRequest(BaseModel):
    name: str  # object name within the org namespace; nested paths allowed


class FileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    key: str
    name: str
    content_type: str
    size_bytes: int
    created_at: datetime


class PresignResponse(BaseModel):
    url: str
    key: str
    expires_in: int
