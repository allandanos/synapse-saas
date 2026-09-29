"""Files: feature gate, multipart upload, download bytes, presign per backend, delete + quota."""

from __future__ import annotations

from httpx import AsyncClient

from tests.conformance.conftest import Tenant, assert_page, assert_problem, grant_feature


async def test_upload_download_delete(api: AsyncClient, tenant: Tenant, platform: dict[str, str]) -> None:
    features = (await api.get("/v1/entitlements", headers=tenant.headers)).json()["features"]
    if "api_access" not in features:  # catalog-dependent: storage may ship on paid tiers only
        gated = await api.post(
            "/v1/files", headers=tenant.headers, files={"file": ("a.txt", b"hello", "text/plain")}
        )
        assert assert_problem(gated, 403, title="feature not entitled")["feature"] == "api_access"
        await grant_feature(api, platform, tenant["org_id"], "api_access")
    uploaded = await api.post(
        "/v1/files", headers=tenant.headers, files={"file": ("a.txt", b"hello", "text/plain")}
    )
    assert uploaded.status_code == 201, uploaded.text
    file_id = uploaded.json()["id"]
    assert uploaded.json()["size_bytes"] == 5 and uploaded.json()["content_type"] == "text/plain"

    listed = assert_page(await api.get("/v1/files", headers=tenant.headers))
    assert [f["id"] for f in listed] == [file_id]

    downloaded = await api.get(f"/v1/files/{file_id}", headers=tenant.headers)
    assert downloaded.status_code == 200 and downloaded.content == b"hello"
    uploaded_rows = await api.get("/v1/audit", headers=tenant.headers, params={"event_type": "file.uploaded"})
    assert [r["target_id"] for r in uploaded_rows.json()["data"]] == [file_id]
    assert downloaded.headers["content-type"].startswith("text/plain")

    summary = await api.get("/v1/usage/summary", headers=tenant.headers)
    assert next(m for m in summary.json()["metrics"] if m["metric"] == "storage_bytes")["used"] == 5

    presign = await api.post(f"/v1/files/{file_id}/presign", headers=tenant.headers)
    if presign.status_code == 200:  # S3-compatible backend
        assert presign.json()["url"].startswith("http")
    else:  # local disk: same problem type as presign-upload
        assert_problem(presign, 409, title="presign unsupported")

    assert (await api.delete(f"/v1/files/{file_id}", headers=tenant.headers)).status_code == 204
    assert_problem(await api.get(f"/v1/files/{file_id}", headers=tenant.headers), 404)
    deleted_rows = await api.get("/v1/audit", headers=tenant.headers, params={"event_type": "file.deleted"})
    assert [r["target_id"] for r in deleted_rows.json()["data"]] == [file_id]
    summary = await api.get("/v1/usage/summary", headers=tenant.headers)
    assert next(m for m in summary.json()["metrics"] if m["metric"] == "storage_bytes")["used"] == 0


async def test_presigned_upload_per_backend(
    api: AsyncClient, tenant: Tenant, platform: dict[str, str]
) -> None:
    features = (await api.get("/v1/entitlements", headers=tenant.headers)).json()["features"]
    if "api_access" not in features:
        await grant_feature(api, platform, tenant["org_id"], "api_access")
    res = await api.post(
        "/v1/files/presign-upload",
        headers=tenant.headers,
        json={"name": "big.bin", "size_bytes": 1024, "content_type": "application/octet-stream"},
    )
    if res.status_code == 200:
        body = res.json()
        assert {"id", "url", "method", "headers", "expires_in"} <= set(body)
        incomplete = await api.post(f"/v1/files/{body['id']}/complete", headers=tenant.headers)
        assert_problem(incomplete, 409, title="upload incomplete")  # nothing was PUT
    else:
        doc = assert_problem(res, 409, title="presign unsupported")
        assert doc["direct_upload_limit_bytes"] > 0
