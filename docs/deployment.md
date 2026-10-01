# Deployment

Four paths: the contributor compose stack (the quickstart), the
published-images compose kit, Kubernetes, and Cloud Run. All use the same
images and the same `SYNAPSE_*` configuration surface, and all white-label
the same way: mount a branding kit and point `SYNAPSE_BRANDING_FILE` at it
on the API, the worker and the migrate step ([Branding](branding.md)).

| Path | Files | Images | Branding kit | Best for |
|---|---|---|---|---|
| Contributor stack | `docker-compose.yml` | built from this checkout | `./config/branding` → `/branding` | developing the framework |
| Published-images kit | [`deploy/compose/`](../deploy/compose/) | `${SYNAPSE_IMAGE_PREFIX:-allandanos}/synapse-saas-{api,worker,web}:${SYNAPSE_VERSION}` | `./branding` → `/branding` | trials, demos, single-host installs |
| Kubernetes | `infrastructure/kubernetes/` | your registry (`image:` refs) | `synapse-branding` ConfigMap → `/branding` (commented in the manifests) | full control, any cloud |
| Cloud Run | `infrastructure/terraform/cloudrun/` | `api_image` / `web_image` vars | bake into a derived API image or mount a Secret/volume; set `SYNAPSE_BRANDING_FILE` | GCP, scale-to-zero-ish, minimal ops |

## Published images (no checkout)

```bash
cd deploy/compose
cp .env.example .env          # set SYNAPSE_SECRET_KEY: openssl rand -base64 32
docker compose up -d --wait   # postgres, redis, migrate, api, worker, web
```

`migrate` validates the branding kit, applies migrations and seeds
permissions, roles and the plan catalog, then exits; api and worker start
after it succeeds. The kit runs with `SYNAPSE_ENV=production`, so the API
refuses a blank or short secret. Details, rebranding and pointing at your own
registry: [`deploy/compose/README.md`](../deploy/compose/README.md). Images
are published by `.github/workflows/release.yml` on `v*` tags
(linux/amd64 + linux/arm64).

## Kubernetes

```bash
cd infrastructure/kubernetes
python3 validate.py                      # structural check, no cluster needed
kubectl apply -f 00-namespace.yaml -f 01-config.yaml
cp 02-secret.example.yaml 02-secret.yaml  # fill real values; gitignored
kubectl apply -f 02-secret.yaml
# …build+push images, update image: refs…
kubectl apply -f 10-api.yaml
kubectl apply -f 11-migrate-job.yaml && kubectl wait --for=condition=complete \
  job/synapse-migrate -n synapse --timeout=180s
kubectl apply -f 12-worker.yaml 13-web.yaml 20-ingress.yaml
```

Details (rolling-update order, autoscaling, what's deliberately absent) in
`infrastructure/kubernetes/README.md`.

## Cloud Run

```bash
cd infrastructure/terraform/cloudrun
terraform init && terraform validate
terraform apply -var='project_id=…' -var='database_url=…' -var='secret_key=…' \
                -var='api_image=…' -var='web_image=…'
gcloud run jobs execute synapse-migrate --region asia-southeast1 --wait
```

The module deploys the API and the console as Cloud Run services, a
`synapse-migrate` job (run once per deploy) and a `synapse-worker-tick` job
that Cloud Scheduler runs every 5 minutes (`synapse-cli jobs run-once --all`:
outbox, deliveries, renewals, partitions, retention). No always-on worker
process is needed on Cloud Run. Full flow in that directory's README.

## Console runtime configuration

The console image (`apps/web/Dockerfile`) has nothing environment-specific
baked in — one image serves every deployment. It reads, at runtime:

| Variable | Default | Purpose |
|---|---|---|
| `SYNAPSE_API_URL` | `http://localhost:8000` | The API origin as **browsers** reach it: API calls, SSO redirects, branding assets |
| `SYNAPSE_API_INTERNAL_URL` | `SYNAPSE_API_URL` | The API origin as the console's **server** reaches it (e.g. `http://api:8000` in compose, the Service DNS name in Kubernetes) |

Name, logo, favicon, colours and footer links come from the API's
`GET /v1/branding` (fetched over the internal URL, memoised for 60 s per
console process; a neutral "Console" fallback while the API is unreachable).
Rebranding is an API-side change (`SYNAPSE_BRANDING_FILE`, then restart the
API and the worker); consoles follow within a minute, no rebuild. Probe the
console at `/healthz` — it answers without the API.

If you add a Content-Security-Policy in front of the console, allow the API
origin in `img-src` (logo, favicon) and `style-src` (optional `custom.css`).
Everything about the branding kit itself is in [Branding](branding.md).

## Production checklist

### Before first exposure

- [ ] `SYNAPSE_SECRET_KEY` rotated from the default (production refuses the
      dev default and anything under 32 characters) — rotating it later
      invalidates stored webhook endpoint secrets (documented in [webhooks](webhooks.md))
- [ ] TLS terminated in front of the API (ingress/Cloud Run HTTPS)
- [ ] `SYNAPSE_WEB_ORIGIN` set to the real console origin (CORS)
- [ ] Console `SYNAPSE_API_URL` set to the public API origin (and
      `SYNAPSE_API_INTERNAL_URL` to the private one, if different)
- [ ] Billing provider configured and its webhook secrets set
- [ ] `SYNAPSE_MANUAL_WEBHOOK_TOKEN` set if the manual provider is reachable
- [ ] Branding kit mounted on API, worker and migrate, and
      `synapse-cli branding validate` green (the API and worker refuse to
      start on an invalid kit)
- [ ] Auth rate limits sized for real traffic (`_PER_IP` defaults to 20/min)
- [ ] `SYNAPSE_TENANT_ISOLATION=app_and_rls` with the API on a `synapse-cli db provision-app-role` role and the worker on the owner DSN (`SYNAPSE_WORKER_DATABASE_URL`) — the API refuses to start if they disagree

### High availability

**Application tier** — stateless by design:

- API holds no session state (JWT + hashed refresh tokens in Postgres); run
  N≥2 replicas behind any load balancer. Both K8s manifests and the Terraform
  module ship 2-replica / min-1-warm defaults with CPU autoscaling.
- Worker is horizontally safe: outbox pickup uses `FOR UPDATE SKIP LOCKED`,
  webhook deliveries claim per-row, usage counters upsert atomically. More
  replicas = more throughput, never double-sends.
- Redis is a *degradation*, not a dependency: without it the framework falls
  back to per-process TTL caches and rate limits. Losing Redis costs cache
  freshness and per-instance limiter accuracy — never correctness.

**Data tier** — the actual HA work:

- Postgres: managed HA (Cloud SQL regional, RDS Multi-AZ, or equivalent).
  The schema is plain Postgres 15+ (jsonb, partitions, citext, pgcrypto) —
  no extensions that block managed offerings.
- Backups: enable PITR (WAL archiving) on the managed instance; verify with
  a monthly restore drill into a scratch instance + `pytest -m pg` against it.
- The outbox means a 5-minute API outage delays webhook deliveries, never
  loses them; delivery retries (1m→5m→30m→2h→6h) absorb multi-hour
  receiver outages on top.

### Disaster recovery

RPO = your Postgres PITR window (typically ≤5 min on managed offerings).
RTO = time to `terraform apply` (or `kubectl apply`) against a fresh cluster
pointed at the restored database — the framework is fully reproducible from
image + schema + config. Recommended drill cadence: quarterly.

**Runbook, in order:**

1. Restore Postgres to the target point (managed PITR).
2. Stand up the stack (apply manifests/terraform) pointed at the restored
   `database_url`.
3. Run the migrate job (idempotent — catches any partial DDL).
4. Verify: `/readyz` green → register a scratch user → create an org →
   confirm the free-plan subscription appears (the bootstrap path exercises
   auth, tenancy, RBAC, plans, and entitlements in one shot).
5. Re-point DNS/ingress.

### Capacity notes

- `usage_events` is monthly-partitioned; the worker pre-creates next month.
  Long retention = drop old partitions (instant) rather than DELETE.
- Audit logs: BRIN-indexed, retention via `SYNAPSE_AUDIT_RETENTION_DAYS`.
- Webhook deliveries purge at 30 days (exhausted ones at 90), published outbox
  rows at 7, audit logs per `SYNAPSE_AUDIT_RETENTION_DAYS`, abandoned
  presigned uploads after twice the presign window — all by `purge_expired`.
- **Object storage**: the local-disk fallback is per container. Any deployment
  with more than one API replica needs `SYNAPSE_S3_BUCKET` (S3, R2, MinIO);
  the K8s manifests mount an `emptyDir` so single-replica trials work.
