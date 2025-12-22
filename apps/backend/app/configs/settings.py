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
    LLM_PROVIDER: Optional[str] = None     # e.g. "anthropic" | "openai"
    LLM_MODEL: str = "claude-sonnet-4-5-20250929"
    TEMPERATURE: float = 0.2
    LLM_CALL_DELAY_SECONDS: float = 5.0    # default spacing; set to 0 to disable

    # NEW: per-provider models (optional)
    ANTHROPIC_MODEL: Optional[str] = None
    OPENAI_MODEL: Optional[str] = None

    # Experiments / trials
    # Human-readable label you use in analysis to group runs
    # e.g. "trial1.baseline", "trial2.memory", "trial3.best", "ablation.rag_off"
    EXPERIMENT_LABEL: str = "trial1.baseline"

    # Prompt context mode for RA chain:
    # "structured"    = full context (features + modules + interfaces + decisions + feedback)
    # "features_only" = features-only ablation (no architecture/feedback context, but full RA prompt)
    # "minimal"       = features-only + basic RA prompt (weakest context engineering)
    PROMPT_CONTEXT_MODE: str = "structured"   # "structured" | "features_only" | "minimal"

    # Feature flags (planning output)
    FEATURE_QA: bool = False             # if False, skip generating acceptance/tests
    FEATURE_DESIGN_NOTES: bool = False   # if False, skip generating tech writer design notes

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
    RAG_COLLECTION: str = "claire-cosine"
    RAG_TOP_K: int = 6
    USE_RAG: bool = False
    RAG_MIN_SIMILARITY: float = 0.35
    RAG_OVERFETCH: int = 2
        # Per-artefact similarity thresholds (stricter for story-level guidance)
    RAG_MIN_SIM_PV: float = 0.40
    RAG_MIN_SIM_TS: float = 0.40
    RAG_MIN_SIM_RA_PLAN: float = 0.45
    RAG_MIN_SIM_STORY_TASKS: float = 0.55

    # Serena / MCP
    SERENA_TRANSPORT: str = "stdio"    # "stdio" | "streamable_http" | "sse"
    SERENA_COMMAND: str = "uvx"        # requires uv installed on host
    SERENA_ARGS: list[str] = [
        "--from", "git+https://github.com/oraios/serena",
        "serena", "start-mcp-server",
        "--context", "ide-assistant",
    ]
    
    # --- Coding / Serena agent execution guards ---
    CODING_RECURSION_LIMIT: int = 100        # LangGraph recursion ceiling
    CODING_MAX_TURNS: int = 10               # (kept) secondary ceiling for agents that support it
    # Loop guard (detect same tool + same args repeated)
    CODING_LOOP_GUARD_ENABLED: bool = True
    CODING_LOOP_WINDOW: int = 6              # look at last N tool calls
    CODING_LOOP_MAX_SAME: int = 3            # abort if the last N are all the same call ≥ this count
    # --- Serena LSP readiness guard ---
    SERENA_LS_READY_MAX_WAIT_SECONDS: float = 20.0   # total time to wait
    SERENA_LS_READY_POLL_INTERVAL_SECONDS: float = 0.75  # between polls
    SERENA_LS_READY_REQUIRE_TOOLS: bool = True  # fail hard if LSP never ready

    SERENA_PROJECT_DIR: str = "./data/code"       # Fallback project dir (per-run workspace overrides)
    CODE_WORKSPACES_ROOT: str = "./data/code"  # default; override via env

    SERENA_ALLOW_SHELL: bool = True
    SERENA_ALLOWED_TOOL_NAMES: list[str] = [
        "list_dir",
        "find_file",
        "read_file",
        "create_text_file",
        "search_for_pattern",
        "get_symbols_overview",
        "find_symbol",
        "find_referencing_symbols",
        "replace_symbol_body",
        "insert_after_symbol",
        "insert_before_symbol",
        "replace_content",
        "rename_symbol",
        "activate_project",
        "get_current_config",
    ]


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
