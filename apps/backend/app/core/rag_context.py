from __future__ import annotations
from typing import Iterable, Tuple, List, Optional, Dict, Any
import logging
import time

from fastapi import Request
from app.configs.settings import get_settings
from app.core.memory import NoOpMemoryStore, MemoryDoc
from app.core.metrics import log_tool_call

logger = logging.getLogger(__name__)

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
    *,
    run_id: Optional[str] = None,
    experiment_label: Optional[str] = None,
    prompt_context_mode: Optional[str] = None,
    phase: str = "planning",
) -> Tuple[str, List[MemoryDoc]]:
    """
    Query vector store and return (formatted_text, raw_hits).

    - Safe if the store is NoOp: returns ("", []).
    - Also logs a tool-call metrics event so you can aggregate RAG usage per
      run × phase later.
    """
    settings = get_settings()
    store = request.app.state.memory
    type_list = list(types)

    # If we're running with a NoOp memory store, bail quickly but still log a "tool" event.
    if isinstance(store, NoOpMemoryStore):
        now = time.time()
        try:
            log_tool_call(
                run_id=run_id or "",
                phase=phase,
                agent="rag",
                tool_type="rag",
                tool_name="rag.search",
                start_time=now,
                end_time=now,
                meta={
                    "experiment_label": experiment_label,
                    "prompt_context_mode": prompt_context_mode,
                    "top_k": top_k or settings.RAG_TOP_K,
                    "types": type_list,
                    "n_hits": 0,
                    "reason": "no-op-store",
                },
            )
        except Exception:
            logger.exception("METRICS: failed to log RAG tool call (no-op store)")
        return "", []

    query = f"{requirement_title}\n\n{requirement_description}".strip()
    where: Dict[str, Any] = {"type": {"$in": type_list}}
    fetch_k = (top_k or settings.RAG_TOP_K) * max(1, settings.RAG_OVERFETCH)

    start = time.time()
    hits = store.search(
        query=query,
        top_k=fetch_k,
        where=where,
        min_similarity=settings.RAG_MIN_SIMILARITY,
    )
    end = time.time()

    logger.info("RAG: %s hits for query", len(hits))
    for h in hits[:5]:
        label = h.meta.get("req_title") or h.meta.get("title") or ""
        logger.info("RAG hit: [%s] %s", h.meta.get("type"), label)

    if not hits:
        # Even with zero hits, we still log the tool metric.
        try:
            log_tool_call(
                run_id=run_id or "",
                phase=phase,
                agent="rag",
                tool_type="rag",
                tool_name="rag.search",
                start_time=start,
                end_time=end,
                meta={
                    "experiment_label": experiment_label,
                    "prompt_context_mode": prompt_context_mode,
                    "top_k": top_k or settings.RAG_TOP_K,
                    "types": type_list,
                    "n_hits": 0,
                },
            )
        except Exception:
            logger.exception("METRICS: failed to log RAG tool call (no hits)")
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

    context_text = "\n".join(lines)

    # Log tool-call metrics with hit count and timing
    try:
        log_tool_call(
            run_id=run_id or "",
            phase=phase,
            agent="rag",
            tool_type="rag",
            tool_name="rag.search",
            start_time=start,
            end_time=end,
            meta={
                "experiment_label": experiment_label,
                "prompt_context_mode": prompt_context_mode,
                "top_k": top_k or settings.RAG_TOP_K,
                "types": type_list,
                "n_hits": len(hits),
            },
        )
    except Exception:
        logger.exception("METRICS: failed to log RAG tool call")

    return context_text, hits
