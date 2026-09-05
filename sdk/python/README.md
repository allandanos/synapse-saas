# synapse-saas-client

Python client SDK for the [Synapse SaaS Framework](../../../README.md) API.

Two credential modes:

- **API key** (`sk_…`) — programmatic org access; the org is pinned
  server-side, no org header needed
- **Access token** — a user session from the console login flow

```python
from synapse_saas_client import SynapseClient

client = SynapseClient("https://api.example.com", api_key="sk_…")
usage = client.usage.summary()
for m in usage["metrics"]:
    print(m["metric"], m["used"], "/", m["limit"])
```

Errors mirror the API's problem+json semantics as typed exceptions —
`SynapseLimitError` (402) carries `metric`/`limit`, `SynapseFeatureGatedError`
(403) carries `feature`/`available_in`.

## Install

Until published to PyPI, install from the repo:

```bash
uv pip install ./sdk/python
```

## Testing

```bash
cd sdk/python
uv run --with httpx --with pytest --no-project \
  python -m pytest test_client.py -q --rootdir=. -c /dev/null
```
