# apps/backend/app/agents/agent.py

import os
from typing import List, Dict, Any, Optional

from langchain_core.prompts import ChatPromptTemplate
from langchain.chat_models import init_chat_model  # v1-friendly initializer

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-7-sonnet-20250219")
API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Where to write LLM logs (env can override; container-safe default)
LOG_FILE_DEFAULT = "/data/logs/llm_responses.log"

# Anthropic server-side web search tool (v20250305)
WEB_SEARCH_TOOL = [
    {
        "type": "web_search_20250305",
        "name": os.getenv("ANTHROPIC_WEB_TOOL_NAME", "web_search"),
        # Optional knobs you can expose later:
        # "max_results": 5,
        # "recency_days": 7,
    }
]

# Create the model via LangChain v1 initializer to avoid constructor drift.
# Do NOT pass unsupported params like max_tokens/timeout/stop at init.
llm = init_chat_model(
    model=MODEL,
    model_provider="anthropic",
    temperature=0.3,
)

# Bind Anthropic-native tools via extra_body on the runnable (LC v1 pattern).
llm_with_search = llm.bind(
    extra_body={
        "tools": WEB_SEARCH_TOOL,
        "tool_choice": {"type": "auto"},  # must be an object, not a bare string
        # If you want to cap response size in the future and your version supports it:
        # "max_output_tokens": 800,
    }
)

base_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a helpful assistant. When questions need up-to-date info, "
            "use the web_search tool and include citations (concise list of links at the end).",
        ),
        ("user", "{user_msg}"),
    ]
)

chain = base_prompt | llm_with_search


def log_llm_response(response: str, log_path: Optional[str] = None) -> None:
    # Use provided path, or env var, or container-safe default
    path = (log_path or os.getenv("LOG_FILE") or LOG_FILE_DEFAULT)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(response)
        f.write("\n" + "=" * 80 + "\n")


def _flatten_text_from_parts(parts: List[Any]) -> str:
    """
    Anthropic (via LangChain) may return a list of content parts when tools are used.
    We keep only the assistant 'text' parts and discard tool traces/results.
    """
    texts: List[str] = []
    for p in parts:
        # Common shape: {"type": "text", "text": "...", "citations": [...]}
        if isinstance(p, dict) and p.get("type") == "text":
            t = p.get("text", "")
            if t:
                texts.append(t)
    return "\n".join(texts).strip() or "[no text]"


def _collect_citation_urls(parts: List[Any]) -> List[str]:
    """Pull URLs from any 'citations' fields in text parts (deduped, order preserved)."""
    seen = set()
    urls: List[str] = []
    for p in parts:
        if isinstance(p, dict) and p.get("type") == "text":
            for c in p.get("citations", []) or []:
                url = (c.get("url") or "").strip()
                if url and url not in seen:
                    seen.add(url)
                    urls.append(url)
    return urls


def run_agent(user_msg: str) -> str:
    # Allow a dev-mode echo when no API key is present
    if not API_KEY:
        response = f"[DEV placeholder] Echo: {user_msg}"
        log_llm_response(response)
        return response

    resp = chain.invoke({"user_msg": user_msg})

    # LangChain v1 returns an AIMessage; its .content can be str or list of parts
    if isinstance(resp.content, str):
        log_llm_response(resp.content)
        return resp.content

    parts = list(resp.content) if isinstance(resp.content, list) else []
    answer = _flatten_text_from_parts(parts)

    # Only append our Sources list if the assistant didn’t already include one
    if "Sources:" not in answer:
        sources = _collect_citation_urls(parts)
        if sources:
            answer += "\n\nSources:\n" + "\n".join(f"- {u}" for u in sources[:8])

    log_llm_response(answer)
    return answer
