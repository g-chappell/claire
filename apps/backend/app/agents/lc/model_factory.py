# apps/backend/app/agents/lc/model_factory.py
from __future__ import annotations
import os
from typing import Any, Optional, cast
from langchain_core.language_models.chat_models import BaseChatModel

def _infer_provider() -> str:
    p = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    if p in {"anthropic", "openai"}:
        return p
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    raise ValueError("No provider selected. Set LLM_PROVIDER=anthropic|openai and the matching API key.")

def make_chat_model(
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    *,
    max_retries: Optional[int] = None,
    timeout: Optional[float] = None,
) -> BaseChatModel:
    """
    Build a Chat model for the configured provider.

    - Adds sane defaults for retries/timeouts (env-overridable):
        LLM_MAX_RETRIES (default 6), LLM_TIMEOUT (default 60s)
    - Handles Anthropic's model/model_name kwarg differences across versions.
    - Handles OpenAI's timeout/request_timeout kwarg differences across versions.
    """
    provider = _infer_provider()

    if temperature is None:
        temperature = float(os.getenv("TEMPERATURE", "0.2"))
    if max_retries is None:
        max_retries = int(os.getenv("LLM_MAX_RETRIES", "6"))
    if timeout is None:
        timeout = float(os.getenv("LLM_TIMEOUT", "60"))

    env_model = os.getenv("LLM_MODEL")
    chosen = model or env_model or ("claude-3-7-sonnet-20250219" if provider == "anthropic" else "gpt-4o-mini")

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic  # type: ignore
        AnthropicCls: Any = ChatAnthropic
        # Prefer model_name, fall back to model
        try:
            return cast(
                BaseChatModel,
                AnthropicCls(
                    model_name=chosen,
                    temperature=temperature,
                    max_retries=max_retries,
                    timeout=timeout,
                ),
            )
        except TypeError:
            return cast(
                BaseChatModel,
                AnthropicCls(
                    model=chosen,
                    temperature=temperature,
                    max_retries=max_retries,
                    timeout=timeout,
                ),
            )

    # provider == "openai"
    from langchain_openai import ChatOpenAI  # type: ignore
    OpenAICls: Any = ChatOpenAI
    try:
        return cast(
            BaseChatModel,
            OpenAICls(
                model=chosen,
                temperature=temperature,
                max_retries=max_retries,
                timeout=timeout,
            ),
        )
    except TypeError:
        # Older/newer versions may use request_timeout
        return cast(
            BaseChatModel,
            OpenAICls(
                model=chosen,
                temperature=temperature,
                max_retries=max_retries,
                request_timeout=timeout,
            ),
        )
