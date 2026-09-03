# Cloud Run deployment

Validated with `terraform validate` (google provider ~> 6.0). Deploys:

- **`synapse-api`** — Cloud Run v2 service, startup probe on `/healthz`,
  min 1 warm instance (configurable) to avoid cold starts on the auth path,
  autoscaling to `max_api_instances`; public invoker (put your LB/IAP in front
  for anything stricter)
- **`synapse-worker-tick`** — Cloud Run **job** for migrations + seeds;
  trigger it on each deploy (see below). The long-running arq worker is a
  K8s/ECS concern — Cloud Run jobs don't fit always-on cron loops cheaply
- Secrets in **Secret Manager**, wired via `secret_key_ref` env vars; one
  least-privilege service account with accessor rights on exactly the three
  synapse secrets

Postgres/Redis are **not created here** — pair with Cloud SQL + Memorystore
(or VPC-reachable instances) and pass `database_url` / `redis_url`.

## First run

```bash
terraform init
terraform apply \
  -var='project_id=my-project' \
  -var='database_url=postgresql+asyncpg://user:pass@HOST:5432/synapse' \
  -var='secret_key=<openssl rand -base64 32>' \
  -var='api_image=asia-southeast1-docker.pkg.dev/my-project/synapse/api:1'

# run migrations + seed (idempotent)
gcloud run jobs execute synapse-worker-tick --region asia-southeast1 --wait
```

## Per-deploy flow

```bash
# 1. push the new image tag
# 2. terraform apply (updates the service revision)
# 3. run the migrate job
gcloud run jobs execute synapse-worker-tick --region asia-southeast1 --wait
# 4. route traffic lands automatically on the new revision (Cloud Run default)
```

## Worker scheduling on GCP

The arq worker needs an always-on process. Two options:

- **Cloud Scheduler → the API**: add an authenticated endpoint that triggers
  one `dispatch_outbox` + `deliver_webhooks` pass (both are SKIP LOCKED-safe,
  idempotent, and complete in seconds). Sub-minute latencies suffer; most
  SaaS webhook flows tolerate 1-minute ticks fine.
- **GKE Autopilot / Cloud Run for jobs with a scheduler**: run the same image
  with `synapse-worker` on a small always-on node — reuse
  `infrastructure/kubernetes/12-worker.yaml`.

## Console (web)

Deploy `web_image` to a second Cloud Run service (or any static host — the
console is a standalone Next.js build) with `NEXT_PUBLIC_API_URL` pointing at
`api_url`. Set `web_origin` here so CORS matches.
