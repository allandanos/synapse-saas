# Cloud Run deployment

Validated with `terraform validate` (google provider ~> 6.0). Deploys:

- **`synapse-api`** — Cloud Run v2 service; startup probe on `/readyz` (503
  until the database answers, so traffic waits for a ready revision),
  liveness on `/healthz`, min 1 warm instance (configurable), autoscaling to
  `max_api_instances`; public invoker (put your LB/IAP in front for anything
  stricter)
- **`synapse-web`** — the console as a second Cloud Run service, pointed at
  the API URL (`deploy_web = false` to skip)
- **`synapse-migrate`** — Cloud Run **job**: `synapse-cli migrate && seed`;
  execute once per deploy
- **`synapse-worker-tick`** — Cloud Run **job**: `synapse-cli jobs run-once
  --all` (outbox dispatch, webhook deliveries, usage rollup, entitlement
  expiry, recurring billing, partitions, retention), triggered by
  **Cloud Scheduler** every `worker_schedule` (default: 5 minutes). Every job
  is idempotent and `SKIP LOCKED`-safe, so overlapping ticks are harmless.
  No always-on process is needed.
- Secrets in **Secret Manager** (`database_url`, `secret_key`, optional
  `redis_url` and `manual_webhook_token`), wired via `secret_key_ref`; one
  least-privilege service account with accessor rights on exactly those
- The required APIs (`run`, `secretmanager`, `cloudscheduler`, `iam`) are
  enabled by the module; pass `vpc_connector` to reach private Cloud SQL /
  Memorystore

Postgres/Redis are **not created here** — pair with Cloud SQL + Memorystore
(or VPC-reachable instances) and pass `database_url` / `redis_url`.

## First run

```bash
terraform init
terraform apply \
  -var='project_id=my-project' \
  -var='database_url=postgresql+asyncpg://user:pass@HOST:5432/synapse' \
  -var='secret_key=<openssl rand -base64 32>' \
  -var='api_image=asia-southeast1-docker.pkg.dev/my-project/synapse/api:1' \
  -var='web_image=asia-southeast1-docker.pkg.dev/my-project/synapse/web:1' \
  -var='manual_webhook_token=<openssl rand -hex 32>'

# schema + seeds (idempotent)
gcloud run jobs execute synapse-migrate --region asia-southeast1 --wait
```

## Per-deploy flow

```bash
# 1. push the new image tags
# 2. terraform apply (updates the service revisions and both jobs)
# 3. run the migrate job
gcloud run jobs execute synapse-migrate --region asia-southeast1 --wait
# 4. traffic lands on the new API revision once /readyz answers 200
```

## Worker cadence

`worker_schedule` is a cron expression for Cloud Scheduler (default
`*/5 * * * *`). Webhook and email latency is bounded by it; for sub-minute
delivery run the always-on `synapse-worker` on GKE instead
(`infrastructure/kubernetes/12-worker.yaml`) and set `worker_schedule` to a
slow safety net (e.g. hourly) or drop the scheduler.

## Console (web)

Deployed by the module as `synapse-web` with `SYNAPSE_API_URL` set to the API
URL at runtime — the console image has nothing baked in, so the published
`synapse-saas-web` image works as is. Its startup probe hits `/healthz`. Set
`web_origin` to the console's public URL so CORS and cookies match
(`terraform output web_url` after the first apply, then re-apply).

The console's name, logo, favicon and colours come from the API
(`GET /v1/branding`), which reads `SYNAPSE_BRANDING_FILE`. To white-label,
bake your branding kit into your API image (or mount it from a Secret/volume)
and set `SYNAPSE_BRANDING_FILE` on the API and the worker job.
