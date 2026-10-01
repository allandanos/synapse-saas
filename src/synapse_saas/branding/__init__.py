"""Per-deployment branding (white-labelling): `branding.yaml` + an assets directory.

The API is the source of truth — the console reads `GET /v1/branding`, while
emails, invoice PDFs and the OpenAPI title read `get_branding()` in-process.
"""
