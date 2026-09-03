"""V1 router aggregation."""

from __future__ import annotations

from fastapi import APIRouter

from synapse_saas.api_keys.router import router as api_keys_router
from synapse_saas.audit.router import router as audit_router
from synapse_saas.authorization.router import router as roles_router
from synapse_saas.billing.router import router as billing_router
from synapse_saas.entitlements.router import router as entitlements_router
from synapse_saas.feature_flags.router import router as feature_flags_router
from synapse_saas.identity.router import router as auth_router
from synapse_saas.storage.router import router as files_router
from synapse_saas.subscriptions.router import router as subscriptions_router
from synapse_saas.tenancy.router import router as orgs_router
from synapse_saas.usage.router import router as usage_router
from synapse_saas.webhooks.router import router as webhooks_router

api_v1 = APIRouter(prefix="/v1")
api_v1.include_router(auth_router)
api_v1.include_router(orgs_router)
api_v1.include_router(roles_router)
api_v1.include_router(subscriptions_router)
api_v1.include_router(entitlements_router)
api_v1.include_router(usage_router)
api_v1.include_router(billing_router)
api_v1.include_router(webhooks_router)
api_v1.include_router(files_router)
api_v1.include_router(feature_flags_router)
api_v1.include_router(api_keys_router)
api_v1.include_router(audit_router)
