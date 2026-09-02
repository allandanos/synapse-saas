"""API keys module — programmatic access to an organization's resources.

Keys are `sk_…` bearer credentials, SHA-256 hashed at rest, scoped to one
organization and an optional subset of permissions. The plaintext is shown
exactly once at creation.
"""

from synapse_saas.api_keys.models import ApiKey

__all__ = ["ApiKey"]
