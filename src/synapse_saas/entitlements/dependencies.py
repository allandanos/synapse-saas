"""Entitlement gates as FastAPI dependencies.

    from synapse_saas.entitlements.dependencies import require_feature

    @router.get("/reports", dependencies=[Depends(require_feature("advanced_reports"))])
    async def reports(...): ...

The gate resolves the tenant first (binding the RLS tenant), then checks the
organization's effective entitlements. A missing feature is a 403 problem
document carrying `feature`, `current_plan`, `available_in`, `upgrade_url`.
"""

from __future__ import annotations

from synapse_saas.authorization.dependencies import require_feature

__all__ = ["require_feature"]
