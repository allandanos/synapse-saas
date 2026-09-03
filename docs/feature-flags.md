# Feature Flags

Deployment-level toggles — **distinct from plan entitlements**:

- Entitlements answer *"what did this organization pay for?"* (billing)
- Flags answer *"is this code path on yet?"* — gradual rollouts, kill switches,
  opt-in betas independent of any plan

## Resolution

```
user override → org override → global default (rollout-aware)
```

- **Unknown flags are off** — new code paths stay dark until deliberately
  enabled; no error, no leak
- **User overrides beat org overrides** — debug a rollout for one person
  without moving the org
- **Deterministic percentage rollout**: `sha256(flag_key:identifier)` buckets
  into 10,000 slots. The same org/user always resolves the same way — no
  flapping between requests, and raising a percentage only ever *adds*
  members (tested monotonic)

## API

Management is platform-admin; evaluation is an org-scoped member check.

| Method | Path | Notes |
|---|---|---|
| GET | `/feature-flags` | list (platform admin) |
| POST | `/feature-flags` | `{key, name, enabled?, rollout_percentage?}` |
| PATCH | `/feature-flags/{key}` | flip default or adjust rollout |
| GET/POST | `/feature-flags/{key}/overrides` | list / set org- or user-scope overrides |
| DELETE | `/feature-flags/overrides/{id}` | remove override (default resumes) |
| GET | `/feature-flags/check/{key}` | resolve for caller's org + user |

## Router gate

```python
from synapse_saas.feature_flags.dependencies import require_flag

@router.get("/new-editor")
async def new_editor(_flag=Depends(require_flag("new-editor"))):
    ...
```

Denied → `403 permission_denied` with `{flag, reason: "feature_flag_disabled"}`.
Unlike the entitlement gate (`require_feature`), there are no upgrade hints —
the flag is off, not unpurchased.

## In code

```python
from synapse_saas.feature_flags.service import FeatureFlagService

if await FeatureFlagService(session).is_enabled(
    "new-editor", organization_id=org_id, user_id=user_id
):
    ...
```

## Data model

- `feature_flags` — key, default enabled, optional rollout_percentage (0–100)
- `feature_flag_overrides` — (flag_key, org XOR user, enabled, note); CASCADE
  with their flag/org/user

## Rollout math

`bucket = sha256(f"{flag}:{identifier}") % 10_000`; enabled when
`bucket < BUCKETS * percentage // 100`. Monotone in `percentage`, uniform in
`identifier`, stable per (flag, identifier) — see `test_rollout.py`.
