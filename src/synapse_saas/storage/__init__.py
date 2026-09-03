"""File storage: S3-compatible backends with org-scoped keys.

Bytes live in the backend (AWS S3 / R2 / MinIO, or local disk as the zero-config
fallback); `stored_files` rows are the org-scoped index. Keys are always
`{org_id}/…` — the tenant boundary applies to files exactly as it does to rows.
"""

from synapse_saas.storage.backend import (
    LocalDiskStorage,
    S3Storage,
    get_storage,
    reset_storage,
    scoped_key,
    validate_key,
)
from synapse_saas.storage.models import StoredFile

__all__ = [
    "LocalDiskStorage",
    "S3Storage",
    "StoredFile",
    "get_storage",
    "reset_storage",
    "scoped_key",
    "validate_key",
]
