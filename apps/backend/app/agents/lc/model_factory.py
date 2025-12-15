# apps/backend/app/agents/lc/model_factory.py
from __future__ import annotations
import os
import time
import threading
from typing import Any, Optional, cast, Dict
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.callbacks.base import BaseCallbackHandler

import logging
logger = logging.getLogger(__name__)

from app.core.metrics import log_llm_call, get_llm_context

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

class MetricsLLMHandler(BaseCallbackHandler):
    """
    Callback that logs *per-API-call* usage using provider usage_metadata.
    Context (run_id/phase/agent/story_id) is taken from app.core.metrics.get_llm_context().
    """

    def __init__(self, provider: str, model_name: str) -> None:
        self.provider = provider
        self.model_name = model_name
        # Map of internal LC run_id -> start_time
        self._starts: dict[str, float] = {}

    def on_llm_start(self, serialized, prompts, **kwargs) -> None:
        run_id = str(kwargs.get("run_id") or "")
        self._starts[run_id] = time.time()

    def on_llm_end(self, response, **kwargs) -> None:
        try:
            run_id_internal = str(kwargs.get("run_id") or "")
            start_time = self._starts.pop(run_id_internal, time.time())
            end_time = time.time()

            # --- Extract usage from response ---
            usage = getattr(response, "usage_metadata", None) or {}
            if not isinstance(usage, dict):
                usage = {}

            # Fallback: some providers put this in llm_output.token_usage / usage
            if (not usage) and hasattr(response, "llm_output"):
                llm_output = getattr(response, "llm_output") or {}
                if isinstance(llm_output, dict):
                    token_usage = (
                        llm_output.get("token_usage")
                        or llm_output.get("usage")
                        or {}
                    )
                    if isinstance(token_usage, dict):
                        usage = token_usage

            input_tokens = int(usage.get("input_tokens") or usage.get("input") or 0)
            output_tokens = int(usage.get("output_tokens") or usage.get("output") or 0)

            # If the provider did not give any usage numbers, skip logging
            if input_tokens == 0 and output_tokens == 0:
                return

            # --- Extract provider request_id for console correlation ---
            request_id: Optional[str] = None

            # 1) Direct attributes on the response object
            for attr in ("request_id", "id"):
                if hasattr(response, attr):
                    val = getattr(response, attr)
                    if isinstance(val, str) and val:
                        request_id = val
                        break

            # 2) response_metadata (Anthropic / OpenAI / others)
            if request_id is None and hasattr(response, "response_metadata"):
                meta = getattr(response, "response_metadata") or {}
                if isinstance(meta, dict):
                    request_id = (
                        meta.get("request_id")
                        or meta.get("id")
                        or meta.get("anthropic_request_id")
                    )

            # 3) llm_output (LangChain ChatResult sometimes stashes it here)
            if request_id is None and hasattr(response, "llm_output"):
                lo = getattr(response, "llm_output") or {}
                if isinstance(lo, dict):
                    request_id = (
                        lo.get("request_id")
                        or lo.get("id")
                        or lo.get("anthropic_request_id")
                    )
                    if request_id is None:
                        rm = lo.get("response_metadata") or {}
                        if isinstance(rm, dict):
                            request_id = (
                                rm.get("request_id")
                                or rm.get("id")
                                or rm.get("anthropic_request_id")
                            )

            # --- Pull context from ContextVar ---
            ctx = get_llm_context() or {}
            run_id = str(ctx.get("run_id") or "unknown")
            phase = str(ctx.get("phase") or "unknown")
            agent = str(ctx.get("agent") or "unknown")
            story_id = ctx.get("story_id")
            tool_name = ctx.get("tool_name")

            # Build metadata payload
            meta_payload: Dict[str, Any] = {"usage_raw": usage}
            if request_id:
                meta_payload["provider_request_id"] = request_id

            log_llm_call(
                run_id=run_id,
                phase=phase,
                agent=agent,
                provider=self.provider,
                model=self.model_name,
                start_time=start_time,
                end_time=end_time,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                story_id=str(story_id) if story_id is not None else None,
                tool_name=tool_name,
                metadata=meta_payload,
                provider_request_id=request_id,   # <--- NEW
            )
        except Exception:
            # Never let metrics kill normal flow
            logger.exception("METRICS: failed to log LLM usage from callback")

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
    callbacks: list[BaseCallbackHandler] = []
    if delay_seconds > 0:
        callbacks.append(GlobalLLMDelayHandler(delay_seconds))

    # Per-call usage metrics handler
    callbacks.append(MetricsLLMHandler(provider=provider, model_name=chosen))
    cb_kwargs: dict[str, Any] = {"callbacks": callbacks}

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
                    **cb_kwargs,
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
                    **cb_kwargs,
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
                **cb_kwargs,
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
                **cb_kwargs,
            ),
        )
