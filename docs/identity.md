# Identity

Two ways in, one user table. The `IdentityProvider` seam
(`identity/provider.py`) hides which is active; the console asks `/v1/meta`.

| `SYNAPSE_IDENTITY_PROVIDER` | Sign-in | Users |
|---|---|---|
| `local` (default) | email + password (argon2), refresh-token rotation | created by `POST /v1/auth/register` |
| `keycloak` | single sign-on: OIDC authorization-code flow with PKCE against a Keycloak realm | linked or JIT-provisioned from the id_token |

Both issue the same JWT access token + rotating refresh token (httpOnly cookie
`synapse_rt`), so everything after login — orgs, API keys, RBAC — is identical.

## SSO flow (Keycloak)

```
console  ──GET /v1/auth/oidc/start?return_to=/dashboard──►  API
           302 → Keycloak /auth?…&state&nonce&code_challenge (S256)
browser  ──signs in at Keycloak──►  302 → API /v1/auth/oidc/callback?code&state
API      consumes state (one shot, 10 min TTL), exchanges code + code_verifier,
         verifies id_token: RS256 vs realm JWKS (cached 1h, refetched on unknown kid),
         iss, aud, exp, nonce → links/creates the user → issues tokens
           302 → console /auth/callback?return_to=… with the refresh cookie set
console  POST /v1/auth/refresh → access token → continues to return_to
```

No token ever travels in a URL. `return_to` must be a same-origin path.

### Linking rules (`IdentityService.link_or_create_oidc_user`)

1. `(provider, sub)` already linked → that user.
2. else the email, **only if the IdP asserts `email_verified: true`** → link
   the existing local account (it keeps its password; SSO becomes an
   additional way in).
3. else create an SSO-only user (`identity_provider=keycloak`, no password).
   If an unverified email collides with a local account the login is refused
   (`email_unverified`) — an unverified claim must never take over an account.

SSO-only users get **401 `{sso_url}`** from the password form so the console
can send them to the right door.

### Settings

```bash
SYNAPSE_IDENTITY_PROVIDER=keycloak
SYNAPSE_KEYCLOAK_BASE_URL=https://id.example.com
SYNAPSE_KEYCLOAK_REALM=synapse
SYNAPSE_KEYCLOAK_CLIENT_ID=synapse-web
SYNAPSE_KEYCLOAK_CLIENT_SECRET=…
SYNAPSE_OIDC_REDIRECT_URI=https://api.example.com/v1/auth/oidc/callback   # behind proxies
SYNAPSE_KEYCLOAK_ALLOW_PASSWORD_GRANT=false   # ROPC proxying is opt-in
SYNAPSE_WEB_ORIGIN=https://console.example.com  # where the callback bounces to
```

Register `https://api.example.com/v1/auth/oidc/callback` as a valid redirect
URI on the Keycloak client (confidential client, standard flow, PKCE S256).

### Local development

`docker compose --profile extras up -d keycloak` imports
`infrastructure/keycloak/realm-dev.json`: realm `synapse`, client `synapse-web`
(secret `dev-client-secret`), users `sso@acme.example.com` (verified) and
`unverified@acme.example.com`, both `password123`. Point the API at
`http://localhost:8080` and the console shows **Continue with single sign-on**.

## Local provider details

- Passwords: argon2id; unknown emails burn the same CPU (no timing enumeration)
- Refresh tokens rotate; reuse outside the grace window revokes the chain
- Auth routes are rate-limited per IP and per identity (`identity/rate_limit.py`)
- Password reset: opaque 202 for unknown emails; token emailed via the outbox
