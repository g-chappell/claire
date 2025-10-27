from __future__ import annotations
from typing import Iterable, Tuple, List
import logging
from fastapi import Request
from app.configs.settings import get_settings
from app.core.memory import NoOpMemoryStore, MemoryDoc

logger = logging.getLogger(__name__)

# Limits to avoid prompt bloat
MAX_SNIPPET_CHARS = 400          # per artifact
MAX_CONTEXT_CHARS = 2000         # total across all artifacts

def _trim(s: str, n: int) -> str:
    s = (s or "").strip()
    return (s[: n - 1] + "…") if len(s) > n else s

def build_rag_context(
    request: Request,
    requirement_title: str,
    requirement_description: str,
    types: Iterable[str] = ("product_vision", "technical_solution"),
    top_k: int | None = None,
) -> Tuple[str, List[MemoryDoc]]:
    """
    Query vector store and return (formatted_text, raw_hits).
    Safe if the store is NoOp: returns ("", []).
    """
    settings = get_settings()
    store = request.app.state.memory

    # If we're running with a NoOp memory store, bail quickly
    if isinstance(store, NoOpMemoryStore):
        return "", []

    query = f"{requirement_title}\n\n{requirement_description}".strip()
    where = {"type": {"$in": list(types)}}
    fetch_k = (top_k or settings.RAG_TOP_K) * max(1, settings.RAG_OVERFETCH)
    hits = store.search(
        query=query,
        top_k=fetch_k,
        where=where or {},
        min_similarity=settings.RAG_MIN_SIMILARITY,
    )

    logger.info("RAG: %s hits for query", len(hits))
    for h in hits[:5]:
        label = h.meta.get("req_title") or h.meta.get("title") or ""
        logger.info("RAG hit: [%s] %s", h.meta.get("type"), label)

    if not hits:
        return "", []

    lines: List[str] = []
    total = 0
    for h in hits:
        meta = (getattr(h, "meta", {}) or {})
        t = meta.get("type", "artifact")
        title = (meta.get("req_title") or meta.get("title") or "").strip()
        head = f"[{t}] {title}".strip()
        snippet = _trim(getattr(h, "text", "").strip(), MAX_SNIPPET_CHARS)
        candidate = f"- {head}: {snippet}"
        if total + len(candidate) > MAX_CONTEXT_CHARS:
            break
        lines.append(candidate)
        total += len(candidate)

    return "\n".join(lines), hits
