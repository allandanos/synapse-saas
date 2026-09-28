# Webhooks (outbound)

Tenant-facing event delivery over a transactional outbox.

## Flow

```
mutation ──same tx──► outbox_events
                          │  worker: dispatch_outbox (every 5s, FOR UPDATE SKIP LOCKED)
                          ▼
                    webhook_deliveries (pending)
                          │  worker: deliver_webhooks (every 15s)
                          ▼
                    POST endpoint  +  X-Synapse-Signature
```

Because the outbox row commits **in the same transaction** as the state
change, an event can never be lost to a crash between "save" and "publish" —
and a failed delivery never blocks the original request.

## Signatures

Every delivery carries a Stripe-style signature over the exact body:

```
X-Synapse-Signature: t=1756646400,v1=hex(hmac_sha256(f"{t}.{body}", secret))
```

Verify on your side:

```python
expected = hmac.new(secret, f"{t}.".encode() + body, hashlib.sha256).hexdigest()
hmac.compare_digest(expected, signature)   # and check |now - t| ≤ 300s
```

## Envelope

```json
{
  "id": "0191…",
  "event_type": "subscription.plan_changed",
  "organization_id": "…",
  "created_at": "2026-08-31T00:00:00Z",
  "data": { … }
}
```

## What an endpoint receives

- Only **public** events. Internal events — `member.invite_email` (carries the
  invite token), `user.password_reset_link`, `invoice.email` — are consumed by
  the in-process email handlers and never fan out. The public `member.invited`
  carries `{email, org_name, membership_id}` and no credential material.
- Only the event types it subscribed to (`events` on the endpoint; an empty
  list means every public event).

## Retries

Deliveries: failures (non-2xx, network errors, >10s) retry with backoff
**1m → 5m → 30m → 2h → 6h**, then `exhausted`. Exhausted deliveries stay
visible for 90 days (routine rows: 30) and can be replayed:

```
POST /v1/webhooks/deliveries/{id}/retry
```

Two workers never POST the same delivery twice (`FOR UPDATE SKIP LOCKED`).

Outbox dispatch (the step that turns an event into deliveries) has its own
ladder: each event runs in a savepoint; a failure records `attempts`,
`last_error` and `next_attempt_at` (5s → 30s → 2m → 10m → 30m → 1h) and
after 8 attempts the row is **dead-lettered** (`dead_at`, metric
`synapse_outbox_dead_lettered_total`) so one poison event can never pin the
batch. Emails are sent only after the dispatch commit — a retry cannot resend
an invite or an invoice.

## Endpoints API

| Endpoint | Purpose |
|---|---|
| `GET/POST /v1/webhooks/endpoints` | List / register (secret shown **once** at creation) |
| `DELETE /v1/webhooks/endpoints/{id}` | Remove |
| `GET /v1/webhooks/deliveries` | Delivery history + status |
| `POST /v1/webhooks/deliveries/{id}/retry` | Replay |

Endpoint secrets are Fernet-encrypted at rest under a SHA-256-derived key from
`SYNAPSE_SECRET_KEY` — rotating that key invalidates stored webhook secrets.

## Event catalog

Canonical types live in `core/events.py`. Not every type is emitted by every
code path today (the audit found roughly a third of the historical vocabulary
unemitted); the list below is the vocabulary an endpoint may subscribe to.

<!-- events:start -->

_Generated from `core/events.py` by `scripts/check_docs.py --fix`; do not edit by hand._

**Public** — fan out to tenant webhook endpoints (subject to each endpoint's `events` filter):

- `agent.disabled`
- `agent.registered`
- `agent.updated`
- `api_key.authenticated`
- `api_key.created`
- `api_key.revoked`
- `entitlement.expired`
- `entitlement.granted`
- `entitlement.revoked`
- `file.deleted`
- `file.uploaded`
- `invoice.created`
- `invoice.failed`
- `invoice.paid`
- `member.invited`
- `member.joined`
- `member.removed`
- `member.role_assigned`
- `member.role_revoked`
- `member.updated`
- `org.created`
- `org.suspended`
- `org.unsuspended`
- `org.updated`
- `role.created`
- `role.deleted`
- `role.updated`
- `subscription.activated`
- `subscription.canceled`
- `subscription.expired`
- `subscription.past_due`
- `subscription.plan_changed`
- `subscription.resumed`
- `subscription.trial_started`
- `subscription.updated`
- `usage.hard_limit_reached`
- `usage.soft_limit_reached`
- `user.logged_out`
- `user.login_failed`
- `user.login_succeeded`
- `user.password_reset_completed`
- `user.password_reset_requested`
- `user.registered`
- `user.token_refreshed`
- `user.token_reuse_detected`
- `webhook.delivered`
- `webhook.delivery_exhausted`
- `webhook.delivery_failed`
- `webhook.endpoint_created`
- `webhook.endpoint_deleted`
- `webhook.endpoint_updated`

**Internal** — consumed in-process only (email handlers); never delivered to a webhook:

- `invoice.email`
- `member.invite_email`
- `user.password_reset_link`

<!-- events:end -->
