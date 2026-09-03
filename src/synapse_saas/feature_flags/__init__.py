"""Feature flags: deployment-level toggles, distinct from plan entitlements.

Entitlements answer "what did this org pay for?" — flags answer "is this code
path on yet?" (gradual rollouts, kill switches, opt-in betas independent of
billing). Resolution: user override → org override → global default with
deterministic percentage rollout.
"""

from synapse_saas.feature_flags.models import FeatureFlag, FeatureFlagOverride
from synapse_saas.feature_flags.service import FeatureFlagService, bucket_of, in_rollout

__all__ = [
    "FeatureFlag",
    "FeatureFlagNotFoundError",
    "FeatureFlagOverride",
    "FeatureFlagService",
    "bucket_of",
    "in_rollout",
]
