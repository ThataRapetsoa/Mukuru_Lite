"""Runtime configuration for the AI layer.

Every knob is environment driven so the same image can run against a local
Person 1 backend, a staging cluster, or the mock transport used in tests.
"""

from __future__ import annotations

import os
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Environment-backed settings."""

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: str = "development"
    log_level: str = "INFO"

    backend_api_url: str = "http://localhost:8000"
    backend_api_prefix: str = "/api/v1"
    backend_api_key: str = ""
    backend_timeout_seconds: float = 15.0
    backend_max_retries: int = 2

    ai_use_mock_backend: bool = True

    ai_llm_enabled: bool = False
    ai_llm_api_key: str = ""
    ai_llm_model: str = "gpt-4o-mini"
    ai_llm_base_url: str = "https://api.openai.com/v1"

    ai_default_language: str = "en"
    ai_allow_language_switch: bool = True

    ai_min_amount: Decimal = Decimal("1.00")
    ai_max_amount: Decimal = Decimal("50000.00")
    ai_confirmation_ttl_seconds: int = 120
    ai_max_transactions_per_session: int = 5

    ai_stt_provider: str = "null"
    ai_tts_provider: str = "null"
    ai_audio_sample_rate: int = 16000
    ai_audio_max_seconds: int = 30

    google_cloud_project: str = ""
    google_cloud_stt_language_codes: str = "en-ZA,zu-ZA,st-ZA"
    azure_speech_key: str = ""
    azure_speech_region: str = "southafrica"
    whisper_model: str = "small"

    cors_origins: str = "*"

    @field_validator("ai_default_language", mode="before")
    @classmethod
    def _normalise_language(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = value.strip().lower()
            mapping = {
                "en": "en",
                "eng": "en",
                "english": "en",
                "en-za": "en",
                "zu": "zu",
                "zulu": "zu",
                "izulu": "zu",
                "zu-za": "zu",
                "st": "st",
                "sot": "st",
                "sesotho": "st",
                "sotho": "st",
                "isisesotho": "st",
                "st-za": "st",
            }
            return mapping.get(cleaned, cleaned)
        return value

    @field_validator("ai_stt_provider", "ai_tts_provider", mode="before")
    @classmethod
    def _lower_provider(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @property
    def base_url(self) -> str:
        """Backend root without the version prefix."""

        return self.backend_api_url.rstrip("/")

    @property
    def api_root(self) -> str:
        """Full versioned API root."""

        prefix = self.backend_api_prefix.strip()
        if prefix and not prefix.startswith("/"):
            prefix = f"/{prefix}"
        return f"{self.base_url}{prefix.rstrip('/')}"

    @property
    def stt_language_codes(self) -> tuple[str, ...]:
        return tuple(
            code.strip()
            for code in self.google_cloud_stt_language_codes.split(",")
            if code.strip()
        )

    @property
    def cors_origin_list(self) -> list[str]:
        raw = self.cors_origins.strip()
        if raw == "*":
            return ["*"]
        return [item.strip() for item in raw.split(",") if item.strip()]

    @property
    def auth_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "X-Client": "mukuru-ai-layer",
        }
        if self.backend_api_key:
            headers["Authorization"] = f"Bearer {self.backend_api_key}"
        return headers


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton.

    Cached so the environment is read once; tests that need different values
    should call :func:`reset_settings_cache`.
    """

    return Settings()


def reset_settings_cache() -> None:
    """Drop the cached settings so the next read re-parses the environment."""

    get_settings.cache_clear()


def configure_for_tests(**overrides: object) -> Settings:
    """Build a settings object from ``overrides`` without touching the env.

    Used by the test-suite so a developer machine's ``.env`` cannot change the
    behaviour of the tests.
    """

    reset_settings_cache()
    return Settings(**overrides)  # type: ignore[arg-type]


def env_flag(name: str, default: bool = False) -> bool:
    """Read a boolean environment variable without the pydantic machinery."""

    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


__all__ = [
    "REPO_ROOT",
    "Settings",
    "configure_for_tests",
    "env_flag",
    "get_settings",
    "reset_settings_cache",
]
