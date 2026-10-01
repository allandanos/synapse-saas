# Synapse SaaS — published images

Run the whole framework (API, worker, console, Postgres, Redis) from the
published Docker images, under your own brand, with no checkout and no build.
Copy this directory anywhere; it is self-contained.

```
deploy/compose/
├── docker-compose.yml   # postgres, redis, migrate, api, worker, web
├── .env.example         # copy to .env — every SYNAPSE_* setting goes here
└── branding/            # your white-label kit: branding.yaml + logo + favicon
```

## Quickstart

```bash
cp .env.example .env
# SYNAPSE_SECRET_KEY is required (≥ 32 characters) — the API refuses to start without it.
# Generate one and paste it into .env:
openssl rand -base64 32
docker compose up -d --wait
```

| Service | URL |
|---|---|
| Console | http://localhost:3000 |
| API + OpenAPI docs | http://localhost:8000/docs |

Register a user, create an organization, and the freemium loop (plans,
limits, upgrade, usage) works with the **manual** billing provider — no
payment accounts needed. Postgres and Redis are not published on host ports.

> **Image availability.** The kit defaults to `SYNAPSE_VERSION=0.2.0`, the
> first release with runtime branding and a runtime API URL. Until `v0.2.0`
> is published to Docker Hub, build the images locally from a checkout of
> the framework and point the kit at them:
>
> ```bash
> # in the framework repository root
> docker build -f apps/api/Dockerfile    -t local/synapse-saas-api:dev .
> docker build -f apps/worker/Dockerfile -t local/synapse-saas-worker:dev .
> docker build -f apps/web/Dockerfile    -t local/synapse-saas-web:dev .
> # back in this directory, in .env
> SYNAPSE_IMAGE_PREFIX=local
> SYNAPSE_VERSION=dev
> ```
>
> The `0.1.0` images predate branding support and do not work with this kit.

## What `migrate` does

`migrate` is a one-shot container from the API image that runs on every
`docker compose up`:

1. `synapse-cli branding validate` — checks `branding/branding.yaml` and its
   assets; a mistake stops the stack here, listing every error.
2. `synapse-cli migrate` — applies the framework's database migrations.
3. `synapse-cli seed` — upserts permissions, system roles and the plan
   catalog (idempotent; no demo users in production).

`api` and `worker` start only after it exits successfully; `web` waits for
the API's health check. Follow it with `docker compose logs migrate`.

## Rebrand

`branding/` is the default kit, fully commented. Edit it in place:

```bash
$EDITOR branding/branding.yaml          # name, tagline, colours, links, email + invoice identity
cp ~/acme/logo.svg branding/logo.svg    # keep the file names, or update the YAML
docker compose restart api worker       # branding is read once per process
```

The console picks the change up within a minute — no rebuild, no restart.
To check a kit before restarting:

```bash
docker compose run --rm migrate "synapse-cli branding validate"
```

Field reference, asset formats, colour tokens, `custom.css`, the landing and
"Powered by" switches, and the fork guide for deeper changes:
[`docs/branding.md`](../../docs/branding.md).

## Configuration

`.env` is read by Compose (image, ports, the console's API URL) and by the
`api`, `worker` and `migrate` containers (every `SYNAPSE_*` setting; the full
list with comments is the repository's root `.env.example`). The compose file
only overrides the stack wiring: database URL, Redis URL and
`SYNAPSE_BRANDING_FILE=/branding/branding.yaml`.

| Variable | Default | Purpose |
|---|---|---|
| `SYNAPSE_IMAGE_PREFIX` | `allandanos` | Registry namespace of the three images |
| `SYNAPSE_VERSION` | `0.2.0` | Image tag (all three move together) |
| `SYNAPSE_API_PORT` / `SYNAPSE_WEB_PORT` | `8000` / `3000` | Host ports |
| `SYNAPSE_SECRET_KEY` | *(blank — required)* | JWT signing + webhook-secret encryption |
| `POSTGRES_PASSWORD` | `synapse` | Bundled Postgres password (set before the first `up`; URL-safe characters only) |
| `SYNAPSE_WEB_ORIGIN` | `http://localhost:3000` | Console origin as browsers see it (CORS, cookies, email links) |
| `SYNAPSE_API_URL` | `http://localhost:8000` | API origin as browsers see it (console API calls, SSO, logo) |
| `SYNAPSE_BILLING_PROVIDER` | `manual` | `manual`, `stripe`, `xendit`, `paymongo`, `paddle` |
| `SYNAPSE_SMTP_*` | unset host ⇒ emails are logged | Outbound mail relay |

The kit runs with `SYNAPSE_ENV=production`: the refresh cookie is `Secure`
(browsers accept that on `http://localhost`; on any other plain-HTTP host set
`SYNAPSE_COOKIE_SECURE=false` for a trial, or put TLS in front), auth rate
limits have production ceilings, and the secret key must be real.

### Behind a domain

Put a TLS-terminating proxy in front of ports 3000 and 8000 and set:

```bash
SYNAPSE_WEB_ORIGIN=https://app.example.com
SYNAPSE_API_URL=https://api.example.com
```

then `docker compose up -d` (the console reads `SYNAPSE_API_URL` at runtime;
nothing is rebuilt).

### Your own registry

Mirror or rebuild the three images under one namespace and set
`SYNAPSE_IMAGE_PREFIX`, e.g. `ghcr.io/acme`:

```bash
# mirror without pulling layers through your machine (multi-arch preserved)
for x in api worker web; do
  docker buildx imagetools create -t ghcr.io/acme/synapse-saas-$x:0.2.0 allandanos/synapse-saas-$x:0.2.0
done
```

A forked console (see the fork guide) only needs its own `web` image; edit
the `web.image` line instead.

## Operations

```bash
docker compose ps                         # health of every service
docker compose logs -f api worker         # follow logs
docker compose pull && docker compose up -d --wait   # upgrade after bumping SYNAPSE_VERSION
docker compose down                       # stop (data kept in volumes)
docker compose down -v                    # stop and delete the database, Redis and stored files
```

Files (invoice PDFs, uploads) go to the shared `storage` volume unless
`SYNAPSE_S3_BUCKET` is set. Back up the `pgdata` volume — or point
`SYNAPSE_DATABASE_URL` at a managed Postgres by editing the compose file —
before relying on this for real customers; see
[`docs/deployment.md`](../../docs/deployment.md) for the production
checklist and the Kubernetes / Cloud Run paths.
