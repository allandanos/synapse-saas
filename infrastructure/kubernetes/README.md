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
kubectl apply -f 12-worker.yaml
kubectl apply -f 13-web.yaml
kubectl apply -f 20-ingress.yaml   # adjust hosts + TLS issuer first
```

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
