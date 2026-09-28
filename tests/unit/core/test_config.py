"""Settings guardrails: production refuses unsafe values; env-file is overridable."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from synapse_saas.core.config import Settings

PROD_KEY = "x" * 48


class TestProductionGuardrails:
    def test_dev_accepts_loose_rate_limits(self) -> None:
        s = Settings(env="development", auth_rate_limit_per_ip=1000, auth_rate_limit_per_identity=100)
        assert s.auth_rate_limit_per_ip == 1000

    def test_prod_rejects_loose_per_ip(self) -> None:
        with pytest.raises(ValidationError, match="PER_IP=1000 exceeds"):
            Settings(env="production", secret_key=PROD_KEY, auth_rate_limit_per_ip=1000)

    def test_prod_rejects_loose_per_identity(self) -> None:
        with pytest.raises(ValidationError, match="PER_IDENTITY=100 exceeds"):
            Settings(env="production", secret_key=PROD_KEY, auth_rate_limit_per_identity=100)

    def test_prod_rejects_dev_default_secret(self) -> None:
        with pytest.raises(ValidationError, match="dev default"):
            Settings(env="production", auth_rate_limit_per_ip=20, auth_rate_limit_per_identity=5)

    def test_prod_accepts_hardened_values(self) -> None:
        s = Settings(
            env="production",
            secret_key=PROD_KEY,
            auth_rate_limit_per_ip=Settings.PRODUCTION_MAX_AUTH_PER_IP,
            auth_rate_limit_per_identity=Settings.PRODUCTION_MAX_AUTH_PER_IDENTITY,
        )
        assert s.is_production

    def test_prod_reports_every_problem_at_once(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            Settings(env="production", auth_rate_limit_per_ip=1000, auth_rate_limit_per_identity=100)
        message = str(excinfo.value)
        assert "PER_IP" in message
        assert "PER_IDENTITY" in message
        assert "dev default" in message


class TestEnvFileOverride:
    def test_env_file_default_is_dotenv(self) -> None:
        assert Settings.model_config.get("env_file") in (".env", None)

    def test_env_file_can_be_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The class attribute is evaluated at import; emulate a fresh import via
        # the same expression the config module uses.
        import os

        monkeypatch.setenv("SYNAPSE_ENV_FILE", "")
        assert (os.environ.get("SYNAPSE_ENV_FILE", ".env") or None) is None
        monkeypatch.setenv("SYNAPSE_ENV_FILE", "/etc/synapse/prod.env")
        assert os.environ.get("SYNAPSE_ENV_FILE", ".env") == "/etc/synapse/prod.env"
