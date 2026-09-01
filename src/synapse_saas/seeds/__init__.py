"""Seeds package: system (idempotent, every deploy) + dev (local only)."""

from synapse_saas.seeds.dev_seed import seed_dev
from synapse_saas.seeds.system_seed import seed_system

__all__ = ["seed_dev", "seed_system"]
