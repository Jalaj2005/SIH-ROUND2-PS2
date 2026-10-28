import os
from dataclasses import dataclass
from functools import lru_cache

try:  # optional convenience; real env vars always win
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

DEV_SECRET = "dev-only-insecure-secret-change-me-0123456789"


def _bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str
    version: str
    environment: str
    database_url: str
    secret_key: str
    access_token_expire_minutes: int
    demo_auth_enabled: bool
    cors_origins: tuple[str, ...]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    settings = Settings(
        app_name="AICTE PS4 Prototype API",
        version="0.1.0",
        environment=os.getenv("ENVIRONMENT", "development").strip().lower(),
        database_url=os.getenv("DATABASE_URL", "sqlite:///./aicte_ps4.db"),
        secret_key=os.getenv("SECRET_KEY", DEV_SECRET),
        access_token_expire_minutes=int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480")),
        demo_auth_enabled=_bool(os.getenv("DEMO_AUTH_ENABLED"), True),
        cors_origins=tuple(
            o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()
        ),
    )
    if settings.is_production and settings.secret_key == DEV_SECRET:
        raise RuntimeError("SECRET_KEY must be set to a non-default value in production.")
    return settings
