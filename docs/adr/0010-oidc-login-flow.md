# ADR 0010: OIDC login is the authorization-code flow, server-side

## Status

Accepted (2026-09-28)

## Context

The Keycloak adapter existed but nothing called it: `get_identity_provider()`
had no caller outside its unit test, the login route verified argon2 hashes
directly, and there was no OIDC callback. The adapter's only login path was
the resource-owner password grant (the console would have proxied passwords
to Keycloak), and it linked users by email without checking that the identity
provider had verified it.

## Decision

- **Authorization-code flow with PKCE, driven by the API.** `GET
  /v1/auth/oidc/start` stores `{code_verifier, nonce, return_to}` under an
  opaque `state` (10-minute TTL, single use) and redirects to the realm. `GET
  /v1/auth/oidc/callback` exchanges the code with the verifier, verifies the
  id_token (RS256 against the realm JWKS — cached an hour, refetched once on an
  unknown `kid` — plus `iss`, `aud`, `exp`, `nonce`), links or creates the user,
  issues the normal token pair, sets the refresh cookie and redirects to the
  console's `/auth/callback`. Tokens never appear in a URL; the console
  finishes with `POST /auth/refresh` like every other session.
- **Linking is subject-first, verified-email-second, create-last.** An
  unverified email never links to or creates over an existing account.
- **SSO-only users are told so.** The password form answers 401 with `sso_url`
  for accounts without a local password.
- **ROPC is opt-in** (`SYNAPSE_KEYCLOAK_ALLOW_PASSWORD_GRANT`), off by default.

## Consequences

- Any OIDC provider that supports the code flow + PKCE + RS256 JWKS works with
  the same adapter shape; Keycloak is the reference (dev realm in
  `infrastructure/keycloak/`).
- `SYNAPSE_OIDC_REDIRECT_URI` exists for deployments behind proxies that
  rewrite scheme/host; otherwise the callback URL is derived from the request.
- The OIDC routes are auth routes for rate limiting (per IP).
- A nightly Playwright job (`e2e-sso`) runs the real Keycloak container; the
  default e2e suite stays local-provider only.
