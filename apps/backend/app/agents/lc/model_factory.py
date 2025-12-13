# apps/backend/app/agents/lc/model_factory.py
from __future__ import annotations
import os
import time
import threading
from typing import Any, Optional, cast
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.callbacks.base import BaseCallbackHandler

import logging
logger = logging.getLogger(__name__)

# --- Claude Models for reference --- 
# haiku fastest/cheapest, sonnet for coding/more expensive, opus most expensive dont use
# versions <4 being deprecated

# claude-haiku-4-5-20251001
# claude-sonnet-4-5-20250929  
# claude-opus-4-1-20250805
# claude-opus-4-20250514
# claude-sonnet-4-20250514
# claude-3-7-sonnet-20250219
# claude-3-5-haiku-20241022
# claude-3-haiku-20240307
# claude-3-opus-20240229

def _infer_provider() -> str:
    p = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    if p in {"anthropic", "openai"}:
        return p
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    raise ValueError("No provider selected. Set LLM_PROVIDER=anthropic|openai and the matching API key.")

# --- Global LLM call spacing (simple process-wide gate) ---
_LLM_RATE_LOCK = threading.Lock()
_LAST_LLM_CALL = 0.0

class GlobalLLMDelayHandler(BaseCallbackHandler):
    def __init__(self, delay: float) -> None:
        self.delay = max(0.0, float(delay))

    def on_llm_start(self, serialized, prompts, **kwargs) -> None:  # sync callback is fine
        if self.delay <= 0:
            return
        global _LAST_LLM_CALL
        with _LLM_RATE_LOCK:
            now = time.monotonic()
            wait = self.delay - (now - _LAST_LLM_CALL)
            if wait > 0:
                time.sleep(wait)
            _LAST_LLM_CALL = time.monotonic()

def make_chat_model(
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    *,
    provider: Optional[str] = None,
    max_retries: Optional[int] = None,
    timeout: Optional[float] = None,
) -> BaseChatModel:
    """
    Build a Chat model for the configured provider.

    - If `provider` is passed, use it (anthropic|openai).
    - Otherwise fall back to env-based _infer_provider().
    """
    if provider:
        provider = provider.strip().lower()
    else:
        provider = _infer_provider()

    if temperature is None:
        temperature = float(os.getenv("TEMPERATURE", "0.2"))
    if max_retries is None:
        max_retries = int(os.getenv("LLM_MAX_RETRIES", "6"))
    if timeout is None:
        timeout = float(os.getenv("LLM_TIMEOUT", "180"))

    env_model = os.getenv("LLM_MODEL")
    chosen = model or env_model or (
        "claude-sonnet-4-5-20250929" if provider == "anthropic" else "gpt-4o-mini"
    )

    # Global inter-call delay (0 = disabled)
    delay_seconds = float(os.getenv("LLM_CALL_DELAY_SECONDS", "0"))
    _callbacks = [GlobalLLMDelayHandler(delay_seconds)] if delay_seconds > 0 else None

    logger.info(
        "LLM_FACTORY provider=%s model=%s env_model=%s temperature=%s max_retries=%s timeout=%s delay=%s",
        provider,
        chosen,
        env_model,
        temperature,
        max_retries,
        timeout,
        delay_seconds,
    )

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
                    **({ "callbacks": _callbacks } if _callbacks else {}),
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
                    **({ "callbacks": _callbacks } if _callbacks else {}),
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
                **({ "callbacks": _callbacks } if _callbacks else {}),
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
                **({ "callbacks": _callbacks } if _callbacks else {}),
            ),
        )
