from __future__ import annotations
import os
from langchain_core.language_models.chat_models import BaseChatModel

def _infer_provider() -> str:
    # Prefer explicit LLM_PROVIDER; otherwise infer from which key is present.
    p = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    if p in {"anthropic", "openai"}:
        return p
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    raise ValueError(
        "No provider selected. Set LLM_PROVIDER=anthropic|openai and the matching API key."
    )

def make_chat_model() -> BaseChatModel:
    provider = _infer_provider()
    temperature = float(os.getenv("TEMPERATURE", "0.2"))

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        model = os.getenv("LLM_MODEL", "claude-3-7-sonnet-20250219")
        return ChatAnthropic(model=model, temperature=temperature)

    # provider == "openai"
    from langchain_openai import ChatOpenAI
    # Pick a sensible default; override via LLM_MODEL when needed.
    model = os.getenv("LLM_MODEL", "gpt-4o-mini")
    return ChatOpenAI(model=model, temperature=temperature)
