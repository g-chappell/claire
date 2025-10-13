# apps/backend/app/configs/settings.py
from __future__ import annotations
from functools import lru_cache

# Pydantic v2 (pydantic-settings) fallback to v1
try:
    from pydantic_settings import BaseSettings, SettingsConfigDict  # v2
    V2 = True
except Exception:
    from pydantic import BaseSettings  # v1
    SettingsConfigDict = None  # type: ignore
    V2 = False


if V2:
    class Settings(BaseSettings):
        # App
        APP_NAME: str = "CLAIRE Backend"
        DEBUG: bool = False
        FRONTEND_ORIGIN: str | None = None  # keep as str for compatibility

        # LLM (informational for manifest)
        LLM_PROVIDER: str | None = None
        LLM_MODEL: str = "claude-3-7-sonnet-20250219"
        TEMPERATURE: float = 0.2

        # DB
        DB_DSN: str = "sqlite:///./data/dev.db"

        # pydantic-settings v2 config
        model_config = SettingsConfigDict(env_file=".env", extra="ignore")
else:
    class Settings(BaseSettings):  # Pydantic v1
        APP_NAME: str = "CLAIRE Backend"
        DEBUG: bool = False
        FRONTEND_ORIGIN: str | None = None

        LLM_PROVIDER: str | None = None
        LLM_MODEL: str = "claude-3-7-sonnet-20250219"
        TEMPERATURE: float = 0.2

        DB_DSN: str = "sqlite:///./data/dev.db"

        class Config:
            env_file = ".env"
            case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()
