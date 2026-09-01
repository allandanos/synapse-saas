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

## Retries

Failures (non-2xx, network errors, >10s) retry with backoff:
**1m → 5m → 30m → 2h → 6h**, then `exhausted`. Exhausted deliveries stay
visible and can be replayed:

```
POST /v1/webhooks/deliveries/{id}/retry
```

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

Canonical types live in `core/events.py`: `org.*`, `member.*`, `subscription.*`,
`entitlement.*`, `invoice.*`, `usage.soft_limit_reached`,
`usage.hard_limit_reached`, `webhook.*`.
