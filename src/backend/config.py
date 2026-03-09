"""
Application configuration via pydantic-settings.

All settings can be overridden via environment variables or a .env file.
Sensitive fields (api keys, tokens) are masked in log output.
"""

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # Mask secrets in repr/logging
        secrets_dir=None,
    )

    # ── Application ────────────────────────────────────────────────────────
    app_name: str = "Copilot Orchestra"
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # ── Copilot CLI ────────────────────────────────────────────────────────
    copilot_cli_path: str | None = None  # None = use bundled or $PATH

    # ── Authentication ─────────────────────────────────────────────────────
    use_logged_in_user: bool = True
    github_token: str | None = None  # GITHUB_TOKEN env var

    # ── BYOK ───────────────────────────────────────────────────────────────
    byok_provider_type: Literal["openai", "anthropic", "azure"] | None = None
    byok_api_key: str | None = None
    byok_base_url: str | None = None

    # ── Default Models ─────────────────────────────────────────────────────
    default_orchestrator_model: str = "claude-sonnet-4.6"
    default_security_model: str = "claude-opus-4.6"
    default_performance_model: str = "claude-sonnet-4.6"
    default_readability_model: str = "claude-haiku-4.5"
    default_synthesizer_model: str = "claude-sonnet-4.6"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str | list) -> list[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    @property
    def byok_active(self) -> bool:
        return self.byok_provider_type is not None and self.byok_api_key is not None

    def safe_repr(self) -> dict:
        """Return settings dict safe for logging (no secrets)."""
        return {
            "app_name": self.app_name,
            "debug": self.debug,
            "log_level": self.log_level,
            "byok_active": self.byok_active,
            "byok_provider_type": self.byok_provider_type,
            "use_logged_in_user": self.use_logged_in_user,
            "github_token_set": self.github_token is not None,
            "default_orchestrator_model": self.default_orchestrator_model,
            "default_security_model": self.default_security_model,
            "default_performance_model": self.default_performance_model,
            "default_readability_model": self.default_readability_model,
            "default_synthesizer_model": self.default_synthesizer_model,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached Settings instance. Call once per process."""
    return Settings()
