# Deployment

Three tiers: local compose (already in the quickstart), Kubernetes, and Cloud
Run. All use the same images and the same `SYNAPSE_*` configuration surface.

| Path | Files | Best for |
|---|---|---|
| Local | `docker-compose.yml` | dev, demos |
| Kubernetes | `infrastructure/kubernetes/` | full control, any cloud |
| Cloud Run | `infrastructure/terraform/cloudrun/` | GCP, scale-to-zero-ish, minimal ops |

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
                -var='api_image=…'
gcloud run jobs execute synapse-worker-tick --region asia-southeast1 --wait
```

Full flow (per-deploy, worker scheduling options) in that directory's README.

## Production checklist

### Before first exposure

- [ ] `SYNAPSE_SECRET_KEY` rotated from the default — rotating it later
      invalidates stored webhook endpoint secrets (documented in [webhooks](webhooks.md))
- [ ] TLS terminated in front of the API (ingress/Cloud Run HTTPS)
- [ ] `SYNAPSE_WEB_ORIGIN` set to the real console origin (CORS)
- [ ] Billing provider configured and its webhook secrets set
- [ ] `SYNAPSE_MANUAL_WEBHOOK_TOKEN` set if the manual provider is reachable
- [ ] Auth rate limits sized for real traffic (`_PER_IP` defaults to 20/min)
- [ ] Consider `SYNAPSE_TENANT_ISOLATION=app_and_rls` for RLS defense-in-depth

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
- Webhook deliveries purge at 30 days by the worker's `purge_expired`.
