# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | ✅ |

## Reporting a vulnerability

Email **allan.danos@gmail.com** with details: affected component, reproduction steps, impact assessment.
Do not open public issues for vulnerabilities.

We will acknowledge within 72 hours and keep you informed of remediation progress.

## Security boundaries this framework maintains

These invariants have dedicated test suites; changes touching them require extra review:

1. **Tenant isolation** — cross-org access must return 404 (not 403), enforced by
   `TenantRepository` auto-filtering and (optionally) Postgres RLS.
2. **Webhook signature verification** — raw request body is read exactly once before parsing;
   signatures are constant-time compared; provider events are deduplicated by
   `provider_webhook_events`.
3. **Refresh token rotation** — tokens are hashed at rest, rotated on every refresh; reuse of a
   rotated token outside the grace window revokes the chain and is audited.
4. **Password storage** — argon2id only.
5. **Money** — integer minor units + ISO-4217 codes. Never floats.

## Deployment checklist

- [ ] `SYNAPSE_SECRET_KEY` rotated from the default (Fernet key material for webhook secrets)
- [ ] `SYNAPSE_MANUAL_WEBHOOK_TOKEN` set if the manual billing provider is exposed
- [ ] `SYNAPSE_TENANT_ISOLATION=app_and_rls` considered for production defense-in-depth
- [ ] TLS terminated in front of the API
- [ ] Provider webhook secrets configured per provider in use
