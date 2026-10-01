# Kubernetes deployment

## Apply order

```bash
kubectl apply -f 00-namespace.yaml
kubectl apply -f 01-config.yaml
cp 02-secret.example.yaml 02-secret.yaml   # edit real values — gitignored
kubectl apply -f 02-secret.yaml

# Build + push images to your registry, then update `image:` in the manifests:
#   docker build -t REGISTRY/synapse-api:TAG -f apps/api/Dockerfile .
#   docker build -t REGISTRY/synapse-web:TAG -f apps/web/Dockerfile .

kubectl apply -f 10-api.yaml
kubectl apply -f 11-migrate-job.yaml
kubectl wait --for=condition=complete job/synapse-migrate -n synapse --timeout=180s
kubectl apply -f 12-worker.yaml 14-pdb.yaml
kubectl apply -f 13-web.yaml
kubectl apply -f 20-ingress.yaml   # adjust hosts + TLS issuer first
```

## White-label (branding)

The console image carries no brand: it reads name, logo, favicon, colours and
links from the API (`GET /v1/branding`), and the API and worker read them from
a branding kit (`branding.yaml` + assets — start one with
`synapse-cli branding init --dir branding`). Ship the kit as a ConfigMap and
uncomment the `branding` volume, mount and `SYNAPSE_BRANDING_FILE` env in
`10-api.yaml`, `11-migrate-job.yaml` and `12-worker.yaml`:

```bash
synapse-cli branding validate --file branding/branding.yaml
kubectl create configmap synapse-branding -n synapse --from-file=branding/ \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl rollout restart deployment/synapse-api deployment/synapse-worker -n synapse
```

Branding is read once per process, hence the restart; consoles pick the change
up within a minute (no web rollout needed). ConfigMaps cap at 1 MiB — keep
logos small (SVG, or an optimised PNG).

The console itself needs only `SYNAPSE_API_URL` (the public API origin) and,
optionally, `SYNAPSE_API_INTERNAL_URL` (in-cluster Service URL) — see
`13-web.yaml`. Its probes hit `/healthz`, which doesn't depend on the API.

## Rolling updates

Migrations are additive and backward-compatible by policy (no destructive
rename without a two-phase rollout), so the safe order is:

1. `kubectl apply -f 11-migrate-job.yaml` (delete the old job first to re-run)
2. wait for completion
3. `kubectl rollout restart deployment/synapse-api synapse-worker -n synapse`

## Autoscaling

- API: 2→10 pods at 70% CPU; raises come from `synapse_http_request_duration_seconds`
- Worker: 2→6 pods at 75% CPU — the outbox guarantees at-least-once via
  `FOR UPDATE SKIP LOCKED`, so extra replicas are always safe

## Metrics

`prometheus.io/*` annotations on the api pods wire `/metrics` into the
Prometheus Operator or annotation-based discovery — no extra scrape config
for the standard install.

## What's deliberately absent

- **No Postgres/Redis manifests**: use managed services (Cloud SQL, RDS,
  Memorystore, ElastiCache) or your platform's operators. Running stateful
  data services by hand in-cluster is how data gets lost.
- **No NetworkPolicies/PodSecurity admission boilerplate**: cluster-specific.
  Apply yours; the workloads run non-root with no privileged requests.

## Storage

The images fall back to local disk under `/data/storage` (an `emptyDir` per
pod in these manifests). That is fine for a single-replica trial and wrong
for anything else: with `replicas: 2` an upload lands on one pod and a
download may hit the other. Set `SYNAPSE_S3_BUCKET` (plus endpoint/keys in
`02-secret.yaml`) for any real deployment — S3, Cloudflare R2 and MinIO all
work — and the presigned upload/download routes become available.

## Hardening that ships

- Non-root, read-only root filesystem, all capabilities dropped, RuntimeDefault
  seccomp on API and worker pods (`/data/storage` and `/tmp` are the only
  writable mounts)
- PodDisruptionBudgets keep one API and one worker pod through drains
- `/readyz` answers 503 when the database is unreachable, so the readiness
  probe really pulls a broken pod out of the Service
