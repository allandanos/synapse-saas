# Branding (white-label)

A Synapse deployment carries **your** product's name, logo, colours and links
— in the console, in transactional emails, on invoice PDFs and in the API
docs — without a fork and without rebuilding an image. Branding is
configuration: a `branding.yaml` plus a few asset files, mounted next to the
API. The API is the single source of truth; the console reads it over HTTP at
runtime, emails and PDFs read it in-process. Decision record:
[ADR 0013](adr/0013-white-labelling.md).

Two tiers:

1. **Reskin** (most deployments): run the published images, mount a branding
   kit. Covered by everything up to [Fork guide](#fork-guide).
2. **Fork the console** when you need layouts, pages or components the kit
   cannot express. The backend stays a dependency; only `apps/web` is yours.

## What you can brand, and what stays framework-identified

| Surface | Branded by the kit | Stays as is |
|---|---|---|
| Console | name, logo, favicon, page titles (`%s · <name>`), primary colour + its foreground, accent token, corner radius, footer links, landing page or straight-to-login, "Powered by Synapse" on/off, an extra stylesheet | layout, copy of the product screens, neutral and status colours (zinc / emerald / amber / red) |
| Emails (plain text) | sender display name, product name in subjects and bodies, footer | sender **address** (`SYNAPSE_SMTP_FROM`) |
| Invoice PDF | logo or wordmark, legal name, address lines, tax ID, page footer | layout; the framework footer line is gone |
| API | OpenAPI `info.title` (`"<name> API"`) and description (tagline), `GET /v1/meta.product` | `/v1/meta.framework` = `synapse-saas` |
| Wire identifiers | — | refresh cookie name, `X-Synapse-Signature` webhook header, JWT issuer, problem `type` URIs (`https://synapse-saas.dev/problems/…`), Prometheus metric names, database/role names, `synapse-cli` |

Wire identifiers are part of the REST contract (SDKs, ports and existing
webhook receivers depend on them); renaming them would be a breaking change
for no visible gain.

## Quickstart (published images)

```bash
synapse-cli branding init --dir branding   # fully commented branding.yaml + logo.svg + favicon.svg
$EDITOR branding/branding.yaml             # name, colours, links …
cp ~/acme/logo.svg ~/acme/favicon.ico branding/
synapse-cli branding validate --file branding/branding.yaml
```

Mount the directory on the **API, the worker and the migrate step** and point
`SYNAPSE_BRANDING_FILE` at the YAML:

```yaml
# docker compose
services:
  api:
    volumes: ["./branding:/branding:ro"]
    environment:
      SYNAPSE_BRANDING_FILE: /branding/branding.yaml
```

[`deploy/compose/`](../deploy/compose/) ships exactly this wiring (its
`branding/` directory is the default kit — edit it in place). Kubernetes: a
`synapse-branding` ConfigMap, already sketched (commented) in
`infrastructure/kubernetes/1{0,1,2}-*.yaml`. Cloud Run: bake the kit into a
derived API image or mount it from a Secret volume.

Apply a change with `docker compose restart api worker` (branding is read once
per process). The console needs no restart: it picks the change up within a
minute.

## `branding.yaml` reference

Unknown keys are rejected at every level (`extra="forbid"`), so a typo fails at
startup instead of silently doing nothing. A section whose keys are all
commented out is the same as `{}`. Source of truth:
`src/synapse_saas/branding/models.py`; the starter kit's comments repeat this
table.

"Single line" text rejects control characters (it lands in email headers and
PDF cells); "multi-line" text allows newlines and tabs but not NUL.

| Field | Type | Default | Validation |
|---|---|---|---|
| `version` | integer | — (**required**) | must be `1` |
| `name` | string | — (**required**) | 1–60 chars, single line |
| `tagline` | string | none | 1–160 chars, single line |
| `logo` | asset name | none (console shows a letter tile) | asset name rules; `.svg` or `.png` |
| `logo_dark` | asset name | none | asset name rules; `.svg` or `.png` |
| `favicon` | asset name | none | asset name rules; `.ico`, `.png` or `.svg` |
| `custom_css` | asset name | none | asset name rules; `.css` |
| `colors.primary` | colour | `#18181b` | `#RRGGBB` |
| `colors.primary_foreground` | colour | `#ffffff` | `#RRGGBB` |
| `colors.accent` | colour | `#2563eb` | `#RRGGBB` |
| `colors.radius` | CSS length | `0.5rem` | number + `px`, `rem` or `em` (e.g. `6px`, `0.75rem`) |
| `links.website` | URL | none | `http://` or `https://`, ≤ 2048 chars, no spaces/quotes/`<>` |
| `links.docs` | URL | none | as above |
| `links.terms` | URL | none | as above |
| `links.privacy` | URL | none | as above |
| `links.support_email` | email | none | a valid email address |
| `email.from_name` | string | a display name already in `SYNAPSE_SMTP_FROM`, else `name` | 1–80 chars, single line |
| `email.footer` | string | `— <name>` + `links.website` when set | 1–500 chars, multi-line |
| `invoice.legal_name` | string | `name` | 1–120 chars, single line |
| `invoice.address_lines` | list of strings | `[]` | ≤ 6 lines, each 1–120 chars, single line |
| `invoice.tax_id` | string | none | 1–60 chars, single line (printed as `Tax ID: …`) |
| `invoice.footer` | string | none | 1–200 chars, multi-line (every PDF page footer) |
| `invoice.logo` | asset name | `logo` | asset name rules; `.svg` or `.png`; never served over HTTP |
| `landing` | `page` \| `redirect` | `page` | — |
| `powered_by` | boolean | `true` | — |

**Asset name rules:** a bare file name in the same directory as
`branding.yaml` — letters, digits, `.`, `_`, `-`, up to 64 characters, no
sub-directories, no leading dot. Every referenced asset must exist; the
loader reports missing ones together with every other error.

## Assets

| Field | Formats | Notes |
|---|---|---|
| `logo` | SVG, PNG | Console header, auth pages, landing (heights 28 / 32 / 56 px; width follows the aspect ratio). Default for the invoice. |
| `logo_dark` | SVG, PNG | Served and listed in `GET /v1/branding`; the stock console has no dark theme and does not use it yet (forks can). |
| `favicon` | ICO, PNG, SVG | Browser tab icon. Ship a 32×32 (or multi-size 16/32/48 ICO); a square SVG scales to every size. |
| `custom_css` | CSS | Linked **last** in the console's `<head>`, so it can override anything. |
| `invoice.logo` | SVG, PNG | PDF only, read in-process. |

**Invoice logos:** the PDF renderer embeds PNG natively and converts SVG
through fpdf2's SVG support, which covers paths and basic shapes but not
everything (filters, some gradients, embedded fonts, CSS). When the image
fails to render the PDF falls back to the `name` wordmark and logs once. For
a faithful invoice set `invoice.logo: logo.png` (a PNG of ~600 px width)
even when the console uses an SVG.

**Serving:** `GET /v1/branding/assets/<name>` answers only for names the YAML
references in `logo`, `logo_dark`, `favicon` or `custom_css`; anything else —
including `branding.yaml` itself and traversal attempts — is a 404 problem.
Responses carry `Cache-Control: public, max-age=86400` and
`X-Content-Type-Options: nosniff`; SVGs additionally get
`Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'` so an
SVG opened directly cannot run script.

**Cache-busting:** asset URLs in `GET /v1/branding` end in `?v=<sha256[:8]>`
of the file content, so replacing `logo.svg` with new bytes changes its URL
and browsers fetch it immediately despite the one-day cache. Keep the file
name; the digest does the work.

**Trust:** SVG and CSS are operator configuration, not user uploads — whoever
can edit the kit can restyle the console. Keep the kit in version control and
review it like code.

## Colour tokens

`colors` become CSS custom properties on the console's `<html>` element and
Tailwind v4 tokens (`apps/web/src/app/globals.css`, `@theme inline`):

| YAML | CSS variable | Tailwind utilities | Used by |
|---|---|---|---|
| `primary` | `--brand-primary` | `bg-primary`, `text-primary`, `ring-primary`, `outline-primary`, `border-primary` | primary buttons, active navigation item, focus rings and outlines, the current plan's ring and badge, usage-meter bars, the letter tile, the top accent bar on auth and landing pages |
| `primary_foreground` | `--brand-primary-foreground` | `text-primary-foreground` | text and icons drawn on `primary` |
| `accent` | `--brand-accent` | `bg-accent`, `text-accent`, … | available to `custom_css` and forks; no stock component uses it yet |
| `radius` | `--brand-radius` | `rounded-lg` | buttons, inputs, nav items, small surfaces (cards use `rounded-xl` and keep Tailwind's default) |

Pick `primary_foreground` with enough contrast against `primary` (WCAG AA:
4.5:1 for body text). Neutrals and status colours are deliberately not
tokens: they carry meaning (success, warning, error) that a brand should not
override.

## Landing page and "Powered by"

- `landing: page` (default): `/` shows the mark, name, tagline, **Sign in**
  and **Create account**, and the footer. `landing: redirect` sends `/`
  straight to `/login` (HTTP 307) — for consoles that live behind a marketing
  site.
- `powered_by: true` (default) adds a "Powered by Synapse" link to the footer
  of the landing and auth pages. `false` hides it. The footer also lists
  whichever of `links.website`, `docs`, `terms`, `privacy` and
  `support_email` are set.

## How it flows

```
branding.yaml + assets ──(SYNAPSE_BRANDING_FILE)──▶ API / worker process
                                                     │  get_branding(): loaded once, cached for the process
            ┌────────────────────────────────────────┼──────────────────────────────┐
            ▼                                        ▼                              ▼
  GET /v1/branding (JSON, max-age=60)        emails (From name,          invoice PDF (issuer
  GET /v1/branding/assets/<name>?v=…         subject, body, footer)      block, logo, footer)
            │
            ▼
  console server: getRuntimeConfig() over SYNAPSE_API_INTERNAL_URL
     memo: fresh 60 s after a success, 5 s after a failure, stale-while-revalidate
     keeps the last good branding through an API outage; neutral "Console" if it never had one
            │
            ▼
  HTML: <html style="--brand-*">, <title>, favicon + logo URLs prefixed with SYNAPSE_API_URL
```

- **API and worker** load and validate the kit at startup and cache it for
  the process lifetime. A change needs a restart of both (the worker sends
  the emails and renders the invoices).
- **Console** renders per request (`force-dynamic`) and never needs the API at
  build time. Only the very first render of a fresh console process waits for
  the branding fetch (2 s timeout); after that renders never block on it.
  During an outage the console keeps the last branding it saw; a console that
  never reached the API shows a neutral "Console" with no logo — never the
  Synapse brand on a white-labelled deployment.
- **Asset URLs** in the JSON are origin-relative (`/v1/branding/assets/…`):
  the console fetches the JSON over the internal URL, but browsers must load
  the files from the public one, so the console prefixes them with
  `SYNAPSE_API_URL`.

## Validate and fail fast

```bash
synapse-cli branding validate                       # SYNAPSE_BRANDING_FILE, else the packaged default
synapse-cli branding validate --file branding/branding.yaml
```

It prints every problem at once (YAML syntax, unknown keys, bad colours,
asset names, missing files) and exits 1. The API and the worker run the same
loader at startup and refuse to start on an invalid kit (`branding_invalid`),
so a broken edit never half-applies. The published-images kit's `migrate`
service runs `branding validate` first, so `docker compose up` stops before
anything else starts.

## Content-Security-Policy

The console ships without a CSP. If you add one in front of it, allow the
API origin in `img-src` (logo, favicon) and, when you use `custom_css`, in
`style-src`:

```
img-src 'self' https://api.example.com data:;
style-src 'self' 'unsafe-inline' https://api.example.com;
connect-src 'self' https://api.example.com;
```

## Fork guide

Fork the console when the kit cannot express what you need: new pages,
different layouts, a dark theme, another font. The backend stays the
published package or image; only `apps/web` becomes yours.

### Where the seams are

| File | What lives there |
|---|---|
| `apps/web/src/app/layout.tsx` | Root layout: `force-dynamic`, `generateMetadata()` (title template, description, favicon), `--brand-*` variables on `<html>`, the `custom_css` link, `RuntimeConfigProvider` |
| `apps/web/src/lib/runtime-config.server.ts` | `getRuntimeConfig()` — the single server-side resolution point: env (`SYNAPSE_API_URL`, `SYNAPSE_API_INTERNAL_URL`), the `/v1/branding` fetch, memo and fallback |
| `apps/web/src/lib/runtime-config.tsx` | Client context: `useRuntimeConfig()`, `useBranding()`; hands the public API URL to `lib/api.ts` |
| `apps/web/src/lib/branding.ts` | `Branding` type (mirrors `BrandingRead`), strict `parseBranding()`, `DEFAULT_BRANDING`, `assetUrl()`, `brandCssVariables()` |
| `apps/web/src/components/brand-mark.tsx` | Logo `<img>` or letter tile, sizes `sm`/`md`/`lg`, optional name beside it |
| `apps/web/src/components/brand-footer.tsx` | Footer links + "Powered by Synapse" |
| `apps/web/src/app/(auth)/layout.tsx` | Frame of login, register, forgot/reset password (route group: URLs unchanged) |
| `apps/web/src/app/page.tsx` | Landing page / `landing: redirect` |
| `apps/web/src/app/globals.css` | `:root` token defaults and the `@theme inline` mapping |
| `apps/web/src/components/app-shell.tsx` | Signed-in chrome: sidebar, top bar, navigation |

### Rules that keep a fork rebase-friendly

- **Add, don't edit.** New pages under new routes, new components in new
  files; touch the seams above rather than the product screens
  (`app/dashboard/**`), which change upstream most often.
- **Style through tokens.** Use `bg-primary`, `text-primary-foreground`,
  `rounded-lg`, or add tokens in `globals.css`; avoid rewriting class lists
  inside upstream components.
- **Keep the data flow.** Read branding through `useBranding()` /
  `getRuntimeConfig()` and the API through `lib/api.ts`; don't hard-code
  URLs or names — the same image should still serve every environment.
- **Keep selectors stable.** The Playwright suite (`apps/web/e2e`) targets
  form labels and roles; keep them so you can run upstream's e2e against your
  fork.
- **Track upstream per release.** Rebase onto release tags (`vX.Y.Z`), not
  `main`, and run `pnpm lint && pnpm build && pnpm e2e` after each.

### Build and run your image

```bash
docker build -f apps/web/Dockerfile -t ghcr.io/acme/console:1.0.0 .   # build context: repo root
```

Then point the `web` service at it (in `deploy/compose/docker-compose.yml`, or
`SYNAPSE_IMAGE_PREFIX` if you publish all three images under one namespace).
The image takes the same runtime env (`SYNAPSE_API_URL`,
`SYNAPSE_API_INTERNAL_URL`) and probe (`/healthz`) as the published one.

## Per-organization branding (later)

Branding is per **deployment** today. The design leaves one seam for
per-tenant branding: the API resolves branding only through `get_branding()`
and the console only through `getRuntimeConfig()`. Per-org branding would
read overrides from `Organization.settings` at those two points (keyed by the
resolved tenant) without touching any consumer.

## Known limitations

- **Restart to apply.** API and worker read the kit once per process;
  consoles follow within 60 s of the API restart (per console replica).
- **Name beside the logo.** The console prints the product name next to the
  logo in the header and on auth pages. A wordmark logo (the name drawn in
  the image) therefore shows the name twice; use a square mark as `logo`, or
  hide the text with `custom_css` in a fork.
- **Logo box before load.** `BrandMark` reserves a square box sized to the
  logo height until the image loads, so a wide logo shifts the name
  sideways once on first paint.
- **No dark theme.** `logo_dark` is served but unused by the stock console.
- **Invoice text is Latin-1.** The PDF uses core Helvetica; characters outside
  Latin-1 in the name, legal name or address print as `?`.
- **SVG in PDFs** — see [Assets](#assets); prefer PNG for `invoice.logo`.
- **Emails are plain text** — no HTML template, no logo in emails.
- **English only.** Console copy and email bodies are not localized.
