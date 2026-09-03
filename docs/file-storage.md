# File Storage

S3-compatible object storage with the tenant boundary extended to bytes: keys
are always `{org_id}/…`, and cross-org access is a 404 exactly like rows.

## Backends

| Backend | When | Presigned URLs |
|---|---|---|
| **S3-compatible** (AWS S3, Cloudflare R2, MinIO) | `SYNAPSE_S3_BUCKET` set | ✅ get + put |
| **Local disk** (default) | no bucket — clone-and-run | ❌ (stream via API) |

```bash
# S3 / R2
SYNAPSE_S3_BUCKET=my-bucket
SYNAPSE_S3_REGION=ap-southeast-1
SYNAPSE_S3_ACCESS_KEY_ID=…
SYNAPSE_S3_SECRET_ACCESS_KEY=…

# MinIO (compose profile: docker compose --profile extras up)
SYNAPSE_S3_ENDPOINT_URL=http://localhost:9000
SYNAPSE_S3_BUCKET=synapse
SYNAPSE_S3_ACCESS_KEY_ID=minioadmin
SYNAPSE_S3_SECRET_ACCESS_KEY=minioadmin

# No bucket at all ⇒ local disk under SYNAPSE_STORAGE_ROOT
```

## API

| Method | Path | Notes |
|---|---|---|
| GET | `/v1/files` | org-scoped listing (`file:read`) |
| POST | `/v1/files` | multipart upload ≤10 MiB (`file:write` + `api_access` feature) |
| GET | `/v1/files/{id}` | stream download (`file:read`) |
| POST | `/v1/files/{id}/presign` | time-limited direct URL (S3 backends) |
| DELETE | `/v1/files/{id}` | soft-delete index row + delete object |

## Quotas and gates

- Uploads **consume `storage_bytes`** — the same atomic metered path as every
  other resource. Breach → `402` with `{metric, limit, upgrade_url}` *before a
  byte is written*
- Uploads require the **`api_access` feature** — storage is a paid-tier
  capability; the 403 carries `available_in` upgrade hints
- Direct multipart uploads cap at 10 MiB; larger objects use presigned PUT URLs
  that bypass the API entirely (quota check stays server-side)

## Key rules (enforced in `storage/backend.py`)

- Every key starts with the org id — `validate_key(key, organization_id=…)`
  raises `TenantViolationError` otherwise
- No `..` traversal, no spaces, no leading slashes; nested paths allowed
- Missing objects are 404s identical to cross-tenant ids — no existence leak

## Data model

`stored_files` is the org-scoped index (key, name, content type, size,
soft-delete). Bytes never touch Postgres; deleting an org cascades the index,
and the backend objects age out with the lifecycle policy you configure
(S3 lifecycle rules / MinIO expiry) — the framework deliberately does not
manage remote lifecycle.
