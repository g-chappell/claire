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

def make_chat_model(model: Optional[str] = None, temperature: Optional[float] = None) -> BaseChatModel:
    """
    Build a Chat model for the configured provider.
    - Accepts optional 'model' (overrides env).
    - Tolerates Anthropic constructor differences across versions (model vs model_name).
    """
    provider = _infer_provider()
    if temperature is None:
        temperature = float(os.getenv("TEMPERATURE", "0.2"))

    env_model = os.getenv("LLM_MODEL")
    chosen = model or env_model or ("claude-3-7-sonnet-20250219" if provider == "anthropic" else "gpt-4o-mini")

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic  # type: ignore
        AnthropicCls: Any = ChatAnthropic
        # Prefer the stub-friendly signature; fall back for older/newer versions.
        try:
            return cast(BaseChatModel, AnthropicCls(model_name=chosen, temperature=temperature, timeout=None, stop=None))
        except TypeError:
            return cast(BaseChatModel, AnthropicCls(model=chosen, temperature=temperature))

    # provider == "openai"
    from langchain_openai import ChatOpenAI  # type: ignore
    OpenAICls: Any = ChatOpenAI
    return cast(BaseChatModel, OpenAICls(model=chosen, temperature=temperature))
