"""Application settings.

Single pydantic-settings entrypoint; every environment variable is `SYNAPSE_`-prefixed.
Loaded once via `get_settings()` (cached) and importable anywhere below the api/worker layer.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PLANS_FILE = REPO_ROOT / "config" / "plans.yaml"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SYNAPSE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Core ────────────────────────────────────────────────────────────────────
    env: str = "development"
    secret_key: str = "dev-only-secret-key-change-me-32-bytes-minimum!"
    database_url: str = "postgresql+asyncpg://synapse:synapse@localhost:5433/synapse"
    redis_url: str = "redis://localhost:6380/0"
    web_origin: str = "http://localhost:3000"
    # app | app_and_rls
    tenant_isolation: str = "app"

    # ── Plans / catalog ─────────────────────────────────────────────────────────
    plans_file: str = str(DEFAULT_PLANS_FILE)
    auto_sync_plans: bool = True

    # ── Identity ────────────────────────────────────────────────────────────────
    identity_provider: str = "local"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    refresh_reuse_grace_seconds: int = 10

    keycloak_base_url: str = ""
    keycloak_realm: str = ""
    keycloak_client_id: str = ""
    keycloak_client_secret: str = ""

    # ── Billing ─────────────────────────────────────────────────────────────────
    billing_provider: str = "manual"
    billing_currency: str = "PHP"
    manual_webhook_token: str = ""

    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    xendit_secret_key: str = ""
    xendit_webhook_token: str = ""

    paymongo_secret_key: str = ""
    paymongo_webhook_secret: str = ""

    # ── Entitlements / usage ────────────────────────────────────────────────────
    grace_on_past_due: bool = True
    default_plan_key: str = "free"

    # ── Email ───────────────────────────────────────────────────────────────────
    smtp_host: str = ""
    smtp_port: int = 1025
    smtp_from: str = "synapse@localhost"

    # ── Storage (S3-compatible; unset ⇒ local disk under storage_root) ────────
    s3_endpoint_url: str = ""  # e.g. http://localhost:9000 for MinIO; "" = AWS
    s3_region: str = "us-east-1"
    s3_bucket: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    storage_root: str = ".storage"  # local-disk fallback when no bucket is set
    storage_presign_seconds: int = 3600

    # ── Retention ───────────────────────────────────────────────────────────────
    audit_retention_days: int = 365

    # ── Rate limiting ───────────────────────────────────────────────────────────
    # Auth endpoints: attempts per window per IP and per target identity.
    auth_rate_limit_per_ip: int = 20
    auth_rate_limit_per_identity: int = 5
    auth_rate_window_seconds: int = 60

    @field_validator("tenant_isolation")
    @classmethod
    def _validate_isolation(cls, v: str) -> str:
        allowed = {"app", "app_and_rls"}
        if v not in allowed:
            msg = f"tenant_isolation must be one of {sorted(allowed)}, got {v!r}"
            raise ValueError(msg)
        return v

    @field_validator("billing_provider")
    @classmethod
    def _validate_provider(cls, v: str) -> str:
        allowed = {"manual", "stripe", "xendit", "paymongo"}
        if v not in allowed:
            msg = f"billing_provider must be one of {sorted(allowed)}, got {v!r}"
            raise ValueError(msg)
        return v

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def rls_enabled(self) -> bool:
        return self.tenant_isolation == "app_and_rls"

    @property
    def access_token_ttl_seconds(self) -> int:
        return self.access_token_ttl_minutes * 60

    @property
    def refresh_token_ttl_seconds(self) -> int:
        return self.refresh_token_ttl_days * 86400


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
