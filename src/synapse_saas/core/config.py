"""Application settings.

Single pydantic-settings entrypoint; every environment variable is `SYNAPSE_`-prefixed.
Loaded once via `get_settings()` (cached) and importable anywhere below the api/worker layer.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, ClassVar, Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PLANS_FILE = REPO_ROOT / "config" / "plans.yaml"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SYNAPSE_",
        # Dev convenience only. Images never contain .env (see .dockerignore);
        # set SYNAPSE_ENV_FILE="" to disable file loading entirely.
        env_file=os.environ.get("SYNAPSE_ENV_FILE", ".env") or None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Core ────────────────────────────────────────────────────────────────────
    env: str = "development"
    secret_key: str = "dev-only-secret-key-change-me-32-bytes-minimum!"
    database_url: str = "postgresql+asyncpg://synapse:synapse@localhost:5433/synapse"
    redis_url: str = "redis://localhost:6380/0"
    # Owner-role DSN for processes that must bypass row-level security
    # (worker, CLI, migrations). Empty ⇒ same as database_url. When RLS is on,
    # database_url should be a NOBYPASSRLS, non-owner role and this the owner.
    worker_database_url: str = ""
    web_origin: str = "http://localhost:3000"
    # Additional console origins (CSV or JSON list): per-tenant subdomains,
    # staging, preview deploys. `web_origin` is always included.
    web_origins: Annotated[list[str], NoDecode] = []
    # Refresh-cookie Secure flag. None ⇒ derived: https web_origin or production.
    cookie_secure: bool | None = None
    # Reverse proxies / load balancers whose X-Forwarded-For chain we trust
    # (CIDRs, CSV or JSON list). Empty ⇒ the socket peer is the client and
    # X-Forwarded-For is ignored — a spoofed header must never bypass the
    # per-IP auth rate limit.
    trusted_proxies: Annotated[list[str], NoDecode] = []
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

    paddle_secret_key: str = ""
    paddle_webhook_secret: str = ""

    # ── Entitlements / usage ────────────────────────────────────────────────────
    grace_on_past_due: bool = True
    default_plan_key: str = "free"

    # ── Invoicing ────────────────────────────────────────────────────────────────
    # Printed in the footer of framework-generated invoices (bank details etc.)
    manual_pay_to_instructions: str = ""

    # ── Email ───────────────────────────────────────────────────────────────────
    # notifier: "smtp" sends through the relay below when smtp_host is set;
    # "noop" logs only (the default when no host is configured).
    notifier: Literal["smtp", "noop"] = "smtp"
    smtp_host: str = ""
    smtp_port: int = 1025
    smtp_from: str = "synapse@localhost"
    smtp_username: str = ""
    smtp_password: str = ""
    # none (MailHog/dev), starttls (587), ssl (465)
    smtp_tls: Literal["none", "starttls", "ssl"] = "none"

    # ── Storage (S3-compatible; unset ⇒ local disk under storage_root) ────────
    s3_endpoint_url: str = ""  # e.g. http://localhost:9000 for MinIO; "" = AWS
    s3_region: str = "us-east-1"
    s3_bucket: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    storage_root: str = ".storage"  # local-disk fallback when no bucket is set
    storage_presign_seconds: int = 3600

    # ── Observability ────────────────────────────────────────────────────────────
    metrics_enabled: bool = True
    # OTel: empty exporter ⇒ tracing compiled in but inert (no-op provider)
    otel_exporter_endpoint: str = ""  # e.g. http://localhost:4317
    otel_service_name: str = "synapse-saas"

    # ── Retention ───────────────────────────────────────────────────────────────
    audit_retention_days: int = 365

    # ── Rate limiting ───────────────────────────────────────────────────────────
    # Auth endpoints: attempts per window per IP and per target identity.
    auth_rate_limit_per_ip: int = 20
    auth_rate_limit_per_identity: int = 5
    auth_rate_window_seconds: int = 60

    @field_validator("web_origins", "trusted_proxies", mode="before")
    @classmethod
    def _csv_or_list(cls, v: object) -> object:
        """Accept `a,b,c` from the environment as well as a JSON list (NoDecode hands us the raw string)."""
        if isinstance(v, str):
            raw = v.strip()
            if raw.startswith("["):
                import json

                return json.loads(raw)
            return [item.strip() for item in raw.split(",") if item.strip()]
        return v

    @field_validator("trusted_proxies")
    @classmethod
    def _validate_cidrs(cls, v: list[str]) -> list[str]:
        import ipaddress

        for cidr in v:
            ipaddress.ip_network(cidr, strict=False)  # raises ValueError on garbage
        return v

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
        allowed = {"manual", "stripe", "xendit", "paymongo", "paddle"}
        if v not in allowed:
            msg = f"billing_provider must be one of {sorted(allowed)}, got {v!r}"
            raise ValueError(msg)
        return v

    # Hard ceilings for production. Dev/e2e raise these to register many users
    # from one IP; a baked .env or a copy-pasted override must not reach prod.
    PRODUCTION_MAX_AUTH_PER_IP: ClassVar[int] = 100
    PRODUCTION_MAX_AUTH_PER_IDENTITY: ClassVar[int] = 20

    @model_validator(mode="after")
    def _production_guardrails(self) -> "Settings":
        if not self.is_production:
            return self
        problems: list[str] = []
        if self.auth_rate_limit_per_ip > self.PRODUCTION_MAX_AUTH_PER_IP:
            problems.append(
                f"SYNAPSE_AUTH_RATE_LIMIT_PER_IP={self.auth_rate_limit_per_ip} exceeds the "
                f"production ceiling of {self.PRODUCTION_MAX_AUTH_PER_IP}"
            )
        if self.auth_rate_limit_per_identity > self.PRODUCTION_MAX_AUTH_PER_IDENTITY:
            problems.append(
                f"SYNAPSE_AUTH_RATE_LIMIT_PER_IDENTITY={self.auth_rate_limit_per_identity} exceeds "
                f"the production ceiling of {self.PRODUCTION_MAX_AUTH_PER_IDENTITY}"
            )
        if self.secret_key.startswith("dev-only-"):
            problems.append("SYNAPSE_SECRET_KEY is the dev default")
        if problems:
            raise ValueError("Refusing to start in production: " + "; ".join(problems))
        return self

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def rls_enabled(self) -> bool:
        return self.tenant_isolation == "app_and_rls"

    @property
    def cors_origins(self) -> list[str]:
        """web_origin first, then the extras, de-duplicated and order-preserving."""
        seen: dict[str, None] = {self.web_origin: None}
        for origin in self.web_origins:
            seen.setdefault(origin, None)
        return list(seen)

    @property
    def cookie_secure_effective(self) -> bool:
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.is_production or self.web_origin.lower().startswith("https://")

    @property
    def access_token_ttl_seconds(self) -> int:
        return self.access_token_ttl_minutes * 60

    @property
    def refresh_token_ttl_seconds(self) -> int:
        return self.refresh_token_ttl_days * 86400


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
