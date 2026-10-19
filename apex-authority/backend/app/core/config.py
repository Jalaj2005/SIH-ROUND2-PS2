"""Environment-driven settings. Secrets are read server-side only and never serialised."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_env: str = "development"
    gemini_api_key: str | None = field(default=None, repr=False)  # repr=False: never log the key
    gemini_model: str | None = None
    ai_provider: str = "gemini"  # gemini | mock | disabled
    ai_timeout_seconds: float = 30.0
    ai_max_retries: int = 1  # retries AFTER the first attempt; clamped to MAX_RETRIES_CEILING
    ai_retry_backoff_seconds: float = 1.0
    aar_require_review_for_export: bool = True
    cors_origins: tuple[str, ...] = ("http://localhost:5173",)

    MAX_RETRIES_CEILING = 3

    @property
    def effective_max_retries(self) -> int:
        return max(0, min(self.ai_max_retries, self.MAX_RETRIES_CEILING))

    @property
    def demo_auth_enabled(self) -> bool:
        return self.app_env in {"development", "test"}


def load_settings() -> Settings:
    e = os.environ.get
    placeholders = {"", "replace_with_your_key"}
    key = e("GEMINI_API_KEY")
    model = e("GEMINI_MODEL")
    return Settings(
        app_env=e("APP_ENV", "development"),
        gemini_api_key=None if key in placeholders or key is None else key,
        gemini_model=None if model in {None, "", "replace_with_supported_model"} else model,
        ai_provider=e("AI_PROVIDER", "gemini").strip().lower(),
        ai_timeout_seconds=float(e("AI_TIMEOUT_SECONDS", "30")),
        ai_max_retries=int(e("AI_MAX_RETRIES", "1")),
        ai_retry_backoff_seconds=float(e("AI_RETRY_BACKOFF_SECONDS", "1.0")),
        aar_require_review_for_export=_bool(e("AAR_REQUIRE_REVIEW_FOR_EXPORT"), True),
        cors_origins=tuple(o.strip() for o in e("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()),
    )
