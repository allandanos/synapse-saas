# ADR 0013 — White-labelling: per-deployment branding as configuration, API as source of truth

- **Status:** accepted (2026-10-01)
- **Deciders:** framework maintainers
- **Supersedes / amends:** extends ADR 0011 (distribution) — the published images become usable as-is

## Context

The framework is open source and ships Docker images
(`synapse-saas-{api,worker,web}`), but nothing about a deployment could be
rebranded without a fork. "Synapse" was typed into six console pages, the
invoice PDF, the OpenAPI title and the CLI; the console's colours were literal
Tailwind `zinc-*` classes; emails carried no product name. Worse, the web image
inlined its API URL at build time (`NEXT_PUBLIC_API_URL`), so the published
console image could not serve any real deployment at all.

Implementors want two things: run the published images with their own name,
logo, colours and links on every surface their customers see (console,
emails, invoices, API docs); and, when that is not enough, a console they can
fork and still rebase.

## Decision

1. **Branding is configuration, per deployment.** A `branding.yaml` plus an
   assets directory, shaped like `plans.yaml`: a packaged default kit inside
   the wheel (`src/synapse_saas/config/branding/`, mirrored at
   `config/branding/` and `deploy/compose/branding/` under a byte-identity
   test), overridden with `SYNAPSE_BRANDING_FILE`. Pydantic models with
   `extra="forbid"`; every error reported at once; `synapse-cli branding
   init|validate`; the API and worker refuse to start on an invalid kit.
2. **The API is the source of truth.** `GET /v1/branding` (public, no tenant)
   returns the presentation subset — name, tagline, origin-relative asset URLs
   with a content-hash `?v=`, colours, links, landing, powered-by — and
   `GET /v1/branding/assets/{name}` serves only the files the YAML names
   (`nosniff`, a sandboxing CSP on SVG, 404 problem otherwise). Emails and the
   invoice PDF read the same models in-process; email and invoice settings
   never leave the API.
3. **The console is environment-agnostic.** `SYNAPSE_API_URL` (browser) and
   `SYNAPSE_API_INTERNAL_URL` (server) are runtime env; the root layout is
   `force-dynamic`, fetches branding per process with a 60 s
   stale-while-revalidate memo, keeps the last good value through an outage,
   and falls back to a neutral "Console" — never to the Synapse brand.
4. **Theming through four tokens** — `primary`, `primary-foreground`,
   `accent`, `radius` — mapped with Tailwind v4 `@theme inline` onto CSS
   variables set on `<html>`. Only primary-action usages consume them;
   neutrals and status colours stay literal. An optional operator
   `custom.css`, served by the API, is linked last.
5. **Two tiers, no plugin machinery.** Tier 1 is the kit on the published
   images (`deploy/compose/`, the scaffold's compose, K8s ConfigMap). Tier 2
   is a fork of `apps/web` with a written guide (`docs/branding.md`) naming
   the seams and the rebase rules.
6. **Framework wire identifiers stay** — cookie name, `X-Synapse-Signature`,
   JWT issuer, problem `type` URIs, metric names, DB names, `/v1/meta.framework`.
   They are contract, not presentation.
7. **Single resolution points.** `get_branding()` (API) and
   `getRuntimeConfig()` (console) are the only places branding is resolved,
   leaving one seam for per-organization branding on `Organization.settings`.
8. **Distribution.** Images are published to Docker Hub by `release.yml` on
   `v*` tags (amd64 + arm64), namespace from a repository variable;
   `deploy/compose/` runs them with no checkout; CI runs that kit end to end,
   rebranded, on every push.

## Alternatives rejected

- **Theme or plugin packages** (an npm/pip "theme" the console loads):
  needs a loader, a versioned extension API and a build per theme — the
  opposite of one image for every deployment. Four tokens plus `custom.css`
  cover the reskin case; a fork covers the rest honestly.
- **Per-organization branding now:** multiplies cache keys, needs tenant
  resolution on public pages (login has no tenant yet) and an admin UI. No
  implementor has asked for it; the single resolution points keep it
  additive.
- **Build-time env for the console** (`NEXT_PUBLIC_*`, build args): one image
  per deployment, and the published image is useless — the defect this ADR
  started from.
- **Console-proxied assets** (the Next server re-serving logo/CSS): a second
  cache layer and a second copy of the asset whitelist and headers, for no
  gain over the browser loading them from the API directly.
- **Absolute asset URLs in `/v1/branding`:** the console fetches the JSON over
  the internal URL (`http://api:8000`), which browsers cannot reach; the API
  does not reliably know its public origin behind proxies. Origin-relative
  URLs let each caller prefix the origin it knows.

## Consequences

- One published web image serves every deployment; rebranding is a file edit
  and an API/worker restart, consoles follow within 60 s.
- The contract grew two public paths and `meta.product`; `info.title` is now
  `"<name> API"`. Ports implement the paths to stay conformant; the SDKs exempt
  them as console presentation surface.
- The API serves operator-supplied SVG and CSS. They are trusted
  configuration, mitigated with a strict name whitelist, `resolve()`
  containment, `nosniff` and an SVG CSP — but whoever edits the kit can
  restyle the console.
- A console added CSP must allow the API origin in `img-src`/`style-src`.
- The invoice PDF's SVG support is best-effort (fpdf2); PNG is the documented
  choice for `invoice.logo`.
- Forks own their divergence: the guide keeps rebases cheap, but upstream
  console changes still have to be merged by hand.
