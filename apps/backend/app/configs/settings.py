from __future__ import annotations
from functools import lru_cache
from typing import Optional, Any

# Detect pydantic v2 vs v1 without confusing the type checker
try:
    from pydantic_settings import BaseSettings as V2BaseSettings  # v2
    V2 = True
except Exception:
    from pydantic import BaseSettings as V1BaseSettings            # v1
    V2 = False


# Common field mixin (pure Python, no BaseSettings here)
class _Common:
    # App
    APP_NAME: str = "Cognitive Learning Agents for Iterative Reflection and Explanation"
    DEBUG: bool = False
    FRONTEND_ORIGIN: Optional[str] = None

    # LLM (informational)
    LLM_PROVIDER: Optional[str] = None
    LLM_MODEL: str = "claude-3-7-sonnet-20250219"
    TEMPERATURE: float = 0.2

    # DB (unified)
    DATABASE_URL: str = "sqlite:///./data/dev.db"  # dev default; prod overrides via env

    # Back-compat alias for any old code using DB_DSN
    @property
    def DB_DSN(self) -> str:
        return self.DATABASE_URL
    
    # RAG memory

    # RAG memory (skeleton only)
    RAG_MODE: str = "off"           # off | manual | auto_approved
    RAG_STORE_PATH: str = "./data/vector"
    RAG_COLLECTION: str = "claire-dev"
    RAG_TOP_K: int = 6
    USE_RAG: bool = False


if V2:
    # Pydantic v2 settings
    class SettingsV2(_Common, V2BaseSettings):  # type: ignore[misc]
        # v2 uses model_config (dict is fine; avoids SettingsConfigDict type issues)
        model_config = {"env_file": ".env", "extra": "ignore"}

    Settings = SettingsV2  # runtime alias
else:
    # Pydantic v1 settings
    class SettingsV1(_Common, V1BaseSettings):  # type: ignore[misc]
        class Config:
            env_file = ".env"
            case_sensitive = True

    Settings = SettingsV1  # runtime alias


@lru_cache()
def get_settings() -> Any:
    return Settings()
