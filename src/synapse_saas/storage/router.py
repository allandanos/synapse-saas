"""File storage endpoints.

Upload/download is feature-gated on `api_access` (storage ships on paid tiers)
and meters `storage_bytes` against the plan quota — the same enforcement path
as every other metered resource.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Request, Response, status
from starlette.datastructures import UploadFile

from synapse_saas.authorization.dependencies import require_permission
from synapse_saas.core.errors import (
    NotFoundError,
    PresignUnsupportedError,
    StorageError,
    UploadIncompleteError,
)
from synapse_saas.core.pagination import PageDep, paginate
from synapse_saas.entitlements.service import EntitlementService
from synapse_saas.identity.dependencies import CurrentUser, SessionDep
from synapse_saas.storage.backend import get_storage, scoped_key
from synapse_saas.storage.models import StoredFile
from synapse_saas.storage.schemas import (
    FileRead,
    PresignResponse,
    PresignUploadRequest,
    PresignUploadResponse,
)
from synapse_saas.tenancy.dependencies import TenantDep
from synapse_saas.usage.service import UsageService

router = APIRouter(prefix="/files", tags=["files"])

MAX_DIRECT_UPLOAD_BYTES = 10 * 1024 * 1024  # larger ⇒ presigned PUT


@router.get("", response_model=list[FileRead])
async def list_files(
    tenant: TenantDep, session: SessionDep, user: CurrentUser, page: PageDep, response: Response
) -> list[FileRead]:
    await require_permission("file:read", user, session, tenant)
    from sqlalchemy import select

    stmt = (
        select(StoredFile)
        .where(
            StoredFile.organization_id == tenant.organization_id,
            StoredFile.deleted_at.is_(None),
            StoredFile.status == "ready",
        )
        .order_by(StoredFile.created_at.desc())
    )
    rows = await paginate(session, stmt, page, response)
    return [FileRead.model_validate(r) for r in rows]


@router.post("", response_model=FileRead, status_code=status.HTTP_201_CREATED)
async def upload_file(
    request: Request,
    tenant: TenantDep,
    session: SessionDep,
    user: CurrentUser,
) -> FileRead:
    """Direct upload (multipart, ≤10 MiB). Larger files use the presigned flow."""
    await require_permission("file:write", user, session, tenant)
    await EntitlementService(session).require_feature(tenant.organization_id, "api_access")

    content_type = request.headers.get("content-type", "")
    if not content_type.startswith("multipart/form-data"):
        raise StorageError("Expected multipart/form-data upload")

    form = await request.form()
    upload = form.get("file")
    if not isinstance(upload, UploadFile):
        raise StorageError("Missing 'file' part")
    data = await upload.read()
    if len(data) > MAX_DIRECT_UPLOAD_BYTES:
        raise StorageError(
            f"Direct upload capped at {MAX_DIRECT_UPLOAD_BYTES // (1024 * 1024)} MiB; use presigned upload"
        )

    # storage_bytes is a GAUGE (bytes currently stored): check capacity before
    # writing a single byte, then move the level. Deleting moves it back down.
    await UsageService(session).adjust_gauge(
        tenant.organization_id, "storage_bytes", len(data)
    )  # 402 on breach

    key = scoped_key(tenant.organization_id, upload.filename or "unnamed")
    await get_storage().put(
        key=key, data=data, content_type=upload.content_type or "application/octet-stream"
    )

    row = StoredFile(
        organization_id=tenant.organization_id,
        key=key,
        name=upload.filename or "unnamed",
        content_type=upload.content_type or "application/octet-stream",
        size_bytes=len(data),
        created_by_user_id=user.id,
    )
    session.add(row)
    await session.flush()
    return FileRead.model_validate(row)


@router.post("/presign-upload", response_model=PresignUploadResponse)
async def presign_upload(
    body: PresignUploadRequest, tenant: TenantDep, session: SessionDep, user: CurrentUser
) -> PresignUploadResponse:
    """Large-file path: reserve the quota, hand out a time-limited PUT URL, and
    index the object as `pending`. The client uploads straight to the bucket and
    then calls `POST /files/{id}/complete`. Local-disk storage answers 409."""
    await require_permission("file:write", user, session, tenant)
    await EntitlementService(session).require_feature(tenant.organization_id, "api_access")
    storage = get_storage()
    if not storage.supports_presigned_upload:
        raise PresignUnsupportedError(
            "Presigned uploads need an S3-compatible backend; use multipart POST /files",
            extras={"direct_upload_limit_bytes": MAX_DIRECT_UPLOAD_BYTES},
        )
    # Reserve the quota now (402 on breach) — released by complete-mismatch, delete, or retention
    await UsageService(session).adjust_gauge(tenant.organization_id, "storage_bytes", body.size_bytes)
    key = scoped_key(tenant.organization_id, body.name)
    url = await storage.presign_put(key=key, content_type=body.content_type)
    row = StoredFile(
        organization_id=tenant.organization_id,
        key=key,
        name=body.name,
        content_type=body.content_type,
        size_bytes=body.size_bytes,
        status="pending",
        created_by_user_id=user.id,
    )
    session.add(row)
    await session.flush()
    from synapse_saas.core.config import get_settings

    return PresignUploadResponse(
        id=row.id,
        key=key,
        url=url,
        headers={"Content-Type": body.content_type},
        expires_in=get_settings().storage_presign_seconds,
    )


@router.post("/{file_id}/complete", response_model=FileRead)
async def complete_upload(
    file_id: UUID, tenant: TenantDep, session: SessionDep, user: CurrentUser
) -> FileRead:
    """Verify the uploaded object (exists, size matches the reservation) and mark it ready.
    A mismatch releases the reservation and answers 409 so the client can retry."""
    await require_permission("file:write", user, session, tenant)
    row = await _get_scoped(file_id, tenant.organization_id, session, statuses=("pending", "ready"))
    if row.status == "ready":
        return FileRead.model_validate(row)  # idempotent
    actual = await get_storage().head(key=row.key)
    if actual is None or actual != row.size_bytes:
        await UsageService(session).adjust_gauge(
            tenant.organization_id, "storage_bytes", -int(row.size_bytes)
        )
        row.deleted_at = datetime.now(UTC)
        # Release first, then report: the 409 must not roll the release back
        await session.commit()
        raise UploadIncompleteError(
            "Object missing or size mismatch; request a new presigned upload",
            extras={"expected_bytes": row.size_bytes, "actual_bytes": actual},
        )
    row.status = "ready"
    await session.flush()
    return FileRead.model_validate(row)


@router.get("/{file_id}")
async def download_file(file_id: UUID, tenant: TenantDep, session: SessionDep, user: CurrentUser) -> Response:
    await require_permission("file:read", user, session, tenant)
    row = await _get_scoped(file_id, tenant.organization_id, session)
    data = await get_storage().get(key=row.key)
    return Response(
        content=data,
        media_type=row.content_type,
        headers={"Content-Disposition": f'attachment; filename="{row.name}"'},
    )


@router.post("/{file_id}/presign", response_model=PresignResponse)
async def presign_download(
    file_id: UUID, tenant: TenantDep, session: SessionDep, user: CurrentUser
) -> PresignResponse:
    """Time-limited direct URL (S3 backends)."""
    await require_permission("file:read", user, session, tenant)
    row = await _get_scoped(file_id, tenant.organization_id, session)
    url = await get_storage().presign_get(key=row.key)
    from synapse_saas.core.config import get_settings

    return PresignResponse(url=url, key=row.key, expires_in=get_settings().storage_presign_seconds)


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(file_id: UUID, tenant: TenantDep, session: SessionDep, user: CurrentUser) -> None:
    """Soft-delete the index row, remove the object, and give the bytes back to the quota."""
    await require_permission("file:write", user, session, tenant)
    row = await _get_scoped(file_id, tenant.organization_id, session, statuses=("pending", "ready"))
    row.deleted_at = datetime.now(UTC)
    await get_storage().delete(key=row.key)
    await UsageService(session).adjust_gauge(tenant.organization_id, "storage_bytes", -int(row.size_bytes))


async def _get_scoped(
    file_id: UUID,
    organization_id: UUID,
    session: SessionDep,
    *,
    statuses: tuple[str, ...] = ("ready",),
) -> StoredFile:
    from sqlalchemy import select

    row = (
        await session.execute(
            select(StoredFile).where(
                StoredFile.id == file_id,
                StoredFile.organization_id == organization_id,
                StoredFile.deleted_at.is_(None),
                StoredFile.status.in_(statuses),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("File not found")  # cross-tenant ⇒ same 404
    return row
