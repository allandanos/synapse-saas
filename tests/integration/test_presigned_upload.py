"""Presigned uploads (P4 / WS-F): objects larger than the direct-upload cap go
straight to the bucket; the API reserves the quota, verifies, and indexes."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.pg


def org_headers(fixture: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {fixture['access_token']}", "X-Org-Id": fixture["org_id"]}


class FakeS3:
    """What the router needs from an S3-compatible backend, minus the network."""

    supports_presigned_upload = True

    def __init__(self) -> None:
        self.objects: dict[str, int] = {}
        self.presigned: list[str] = []

    async def presign_put(self, *, key: str, content_type: str) -> str:
        self.presigned.append(key)
        return f"https://bucket.example.test/{key}?X-Amz-Signature=fake"

    async def head(self, *, key: str) -> int | None:
        return self.objects.get(key)

    async def delete(self, *, key: str) -> None:
        self.objects.pop(key, None)

    async def get(self, *, key: str) -> bytes:
        return b"x" * self.objects[key]

    async def put(self, *, key: str, data: bytes, content_type: str) -> str:
        self.objects[key] = len(data)
        return key

    async def presign_get(self, *, key: str) -> str:
        return f"https://bucket.example.test/{key}"


@pytest.fixture
def fake_s3(monkeypatch: pytest.MonkeyPatch) -> FakeS3:
    import synapse_saas.storage.router as router_module

    backend = FakeS3()
    monkeypatch.setattr(router_module, "get_storage", lambda: backend)
    return backend


async def _used(client: AsyncClient, fixture: dict[str, str]) -> int:
    res = await client.get(
        "/v1/usage/check", headers=org_headers(fixture), params={"metric": "storage_bytes"}
    )
    return int(res.json()["used"])


class TestPresignedFlow:
    async def test_presign_then_complete(self, client: AsyncClient, org_and_tokens, fake_s3: FakeS3) -> None:
        headers = org_headers(org_and_tokens)
        res = await client.post(
            "/v1/files/presign-upload",
            headers=headers,
            json={"name": "big/video.mp4", "content_type": "video/mp4", "size_bytes": 50_000_000},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["method"] == "PUT" and body["headers"] == {"Content-Type": "video/mp4"}
        assert body["url"].startswith("https://bucket.example.test/")
        assert fake_s3.presigned == [body["key"]]
        # quota reserved up front; pending rows are not listed yet
        assert await _used(client, org_and_tokens) == 50_000_000
        assert (await client.get("/v1/files", headers=headers)).json() == []

        fake_s3.objects[body["key"]] = 50_000_000  # the client uploaded
        done = await client.post(f"/v1/files/{body['id']}/complete", headers=headers)
        assert done.status_code == 200, done.text
        assert done.json()["status"] == "ready" and done.json()["size_bytes"] == 50_000_000
        listed = (await client.get("/v1/files", headers=headers)).json()
        assert [f["id"] for f in listed] == [body["id"]]
        # idempotent
        assert (await client.post(f"/v1/files/{body['id']}/complete", headers=headers)).status_code == 200

    async def test_complete_with_size_mismatch_releases_the_reservation(
        self, client: AsyncClient, org_and_tokens, fake_s3: FakeS3
    ) -> None:
        headers = org_headers(org_and_tokens)
        body = (
            await client.post(
                "/v1/files/presign-upload", headers=headers, json={"name": "a.bin", "size_bytes": 1_000}
            )
        ).json()
        fake_s3.objects[body["key"]] = 999  # truncated upload
        done = await client.post(f"/v1/files/{body['id']}/complete", headers=headers)
        assert done.status_code == 409, done.text
        assert done.json()["title"] == "upload incomplete"
        assert done.json()["expected_bytes"] == 1_000 and done.json()["actual_bytes"] == 999
        assert await _used(client, org_and_tokens) == 0  # reservation given back
        assert (await client.post(f"/v1/files/{body['id']}/complete", headers=headers)).status_code == 404

    async def test_complete_without_an_object_409(
        self, client: AsyncClient, org_and_tokens, fake_s3: FakeS3
    ) -> None:
        headers = org_headers(org_and_tokens)
        body = (
            await client.post(
                "/v1/files/presign-upload", headers=headers, json={"name": "b.bin", "size_bytes": 10}
            )
        ).json()
        done = await client.post(f"/v1/files/{body['id']}/complete", headers=headers)
        assert done.status_code == 409 and done.json()["actual_bytes"] is None

    async def test_presign_is_quota_checked(
        self, client: AsyncClient, org_and_tokens, fake_s3: FakeS3
    ) -> None:
        """Free plan: 1 GiB. Reserving more is the same 402 an upload would get."""
        res = await client.post(
            "/v1/files/presign-upload",
            headers=org_headers(org_and_tokens),
            json={"name": "huge.bin", "size_bytes": 2 * 1024 * 1024 * 1024},
        )
        assert res.status_code == 402, res.text
        assert res.json()["metric"] == "storage_bytes"
        assert fake_s3.presigned == []

    async def test_abandoned_pending_upload_can_be_deleted(
        self, client: AsyncClient, org_and_tokens, fake_s3: FakeS3
    ) -> None:
        headers = org_headers(org_and_tokens)
        body = (
            await client.post(
                "/v1/files/presign-upload", headers=headers, json={"name": "c.bin", "size_bytes": 500}
            )
        ).json()
        assert (await client.delete(f"/v1/files/{body['id']}", headers=headers)).status_code == 204
        assert await _used(client, org_and_tokens) == 0

    async def test_retention_reclaims_stale_pending_uploads(
        self, client: AsyncClient, org_and_tokens, fake_s3: FakeS3
    ) -> None:
        from sqlalchemy import text

        from synapse_saas.worker.jobs import purge_expired
        from tests.integration.conftest import owner_session_factory

        headers = org_headers(org_and_tokens)
        body = (
            await client.post(
                "/v1/files/presign-upload", headers=headers, json={"name": "d.bin", "size_bytes": 700}
            )
        ).json()
        async with owner_session_factory()() as session:
            await session.execute(
                text("UPDATE stored_files SET created_at = now() - interval '1 day' WHERE id = :id"),
                {"id": body["id"]},
            )
            await session.commit()
        await purge_expired({})
        assert await _used(client, org_and_tokens) == 0
        assert (await client.post(f"/v1/files/{body['id']}/complete", headers=headers)).status_code == 404


class TestLocalBackend:
    async def test_local_disk_answers_409(
        self, client: AsyncClient, org_and_tokens, tmp_path, monkeypatch
    ) -> None:
        import synapse_saas.storage.backend as backend_module
        from synapse_saas.core.config import get_settings

        monkeypatch.setenv("SYNAPSE_S3_BUCKET", "")
        monkeypatch.setenv("SYNAPSE_STORAGE_ROOT", str(tmp_path))
        get_settings.cache_clear()
        backend_module._backend = None
        try:
            res = await client.post(
                "/v1/files/presign-upload",
                headers=org_headers(org_and_tokens),
                json={"name": "x.bin", "size_bytes": 10},
            )
            assert res.status_code == 409, res.text
            assert res.json()["title"] == "presign unsupported"
            assert res.json()["direct_upload_limit_bytes"] == 10 * 1024 * 1024
        finally:
            backend_module._backend = None
            get_settings.cache_clear()
