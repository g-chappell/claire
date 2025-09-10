import os
from typing import List, Dict, Any
from langchain_core.prompts import ChatPromptTemplate
from langchain_anthropic import ChatAnthropic

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-7-sonnet-20250219")
API_KEY = os.getenv("ANTHROPIC_API_KEY")

WEB_SEARCH_TOOL = [
    {
        "type": "web_search_20250305",   # ← was "web_search"
        "name": os.getenv("ANTHROPIC_WEB_TOOL_NAME", "web_search"),
        # optional knobs Anthropic supports:
        # "max_results": 5,
        # "recency_days": 7,
    }
]

llm = ChatAnthropic(
    model=MODEL,
    temperature=0.3,
    max_tokens=800,
    # either pass directly...
    tools=WEB_SEARCH_TOOL,
    tool_choice={"type": "auto"},        # ← must be an object, not "auto"
    # ...or keep extra_body if you prefer:
    # extra_body={"tools": WEB_SEARCH_TOOL, "tool_choice": {"type": "auto"}},
)

#llm_with_tools = llm.bind_tools([WEB_SEARCH_TOOL])

base_prompt = ChatPromptTemplate.from_messages([
    ("system",
     "You are a helpful assistant. When questions need up-to-date info, "
     "use the web_search tool and include citations (concise list of links at the end)."),
    ("user", "{user_msg}")
])

chain = base_prompt | llm


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
    if not API_KEY:
        return f"[DEV placeholder] Echo: {user_msg}"

    resp = chain.invoke({"user_msg": user_msg})

    if isinstance(resp.content, str):
        return resp.content

    parts = list(resp.content) if isinstance(resp.content, list) else []
    answer = _flatten_text_from_parts(parts)

    # Only append our Sources list if Claude didn't already add one
    if "Sources:" not in answer:
        sources = _collect_citation_urls(parts)
        if sources:
            answer += "\n\nSources:\n" + "\n".join(f"- {u}" for u in sources[:8])

    return answer
