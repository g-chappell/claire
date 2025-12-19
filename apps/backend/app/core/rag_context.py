from __future__ import annotations
from typing import Iterable, Tuple, List, Optional, Dict, Any
import logging
import time
import hashlib

from fastapi import Request
from app.configs.settings import get_settings
from app.core.memory import NoOpMemoryStore, MemoryDoc
from app.core.metrics import log_tool_call

logger = logging.getLogger(__name__)


# Limits to avoid prompt bloat
MAX_SNIPPET_CHARS = 400          # per artifact
MAX_CONTEXT_CHARS = 2000         # total across all artifacts

def _trim(s: str, n: int) -> str:
    s = (s or "").strip()
    return (s[: n - 1] + "…") if len(s) > n else s

def _preview(s: str, n: int = 240) -> str:
    s = (s or "").replace("\n", "\\n").strip()
    return (s[: n - 1] + "…") if len(s) > n else s

def _sha1(s: str) -> str:
    return hashlib.sha1((s or "").encode("utf-8")).hexdigest()[:10]

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

    logger.info(
        "RAG_CTX_QUERY phase=%s run=%s types=%s top_k=%s fetch_k=%s min_sim=%s q_len=%d q_sha1=%s q_prev=%s",
        phase,
        run_id,
        type_list,
        top_k or settings.RAG_TOP_K,
        fetch_k,
        settings.RAG_MIN_SIMILARITY,
        len(query),
        _sha1(query),
        _preview(query, 240),
    )
    logger.info("RAG_CTX_WHERE where=%s", where)

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
        logger.info("RAG hit preview: id=%s len=%d prev=%s", h.id, len(h.text or ""), _preview(h.text or "", 240))

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

MAX_EXEMPLAR_CHARS = 6000  # single exemplar cap to avoid token bloat

def build_exemplar_context(
    request: Request,
    *,
    query_title: str,
    query_description: str,
    artifact_type: str,
    top_k: int = 1,
    run_id: Optional[str] = None,
    experiment_label: Optional[str] = None,
    prompt_context_mode: Optional[str] = None,
    phase: str = "planning",
) -> Tuple[str, List[MemoryDoc]]:
    """
    Retrieve TOP-1 exemplar for a single artefact type.
    Returns (exemplar_text, raw_hits). If no hits, returns ("", []).
    """
    settings = get_settings()
    store = request.app.state.memory

    # No-op store guard (still log)
    if isinstance(store, NoOpMemoryStore):
        now = time.time()
        try:
            log_tool_call(
                run_id=run_id or "",
                phase=phase,
                agent="rag",
                tool_type="rag",
                tool_name="rag.exemplar_search",
                start_time=now,
                end_time=now,
                meta={
                    "experiment_label": experiment_label,
                    "prompt_context_mode": prompt_context_mode,
                    "artifact_type": artifact_type,
                    "top_k": top_k,
                    "n_hits": 0,
                    "reason": "no-op-store",
                },
            )
        except Exception:
            logger.exception("METRICS: failed to log RAG exemplar tool call (no-op store)")
        return "", []

    query = f"{(query_title or '').strip()}\n\n{(query_description or '').strip()}".strip()
    where: Dict[str, Any] = {"type": artifact_type}
    if run_id:
        # prevent self-retrieval / leakage into the same run
        where["run_id"] = {"$ne": str(run_id)}

    fetch_k = max(1, top_k) * max(1, settings.RAG_OVERFETCH)

    # ---- DEBUG START (TEMP) ----
    logger.info(
        "RAG_EX_QUERY phase=%s run=%s type=%s top_k=%s fetch_k=%s title_len=%d desc_len=%d q_len=%d q_sha1=%s title_prev=%s desc_prev=%s",
        phase,
        run_id,
        artifact_type,
        top_k,
        fetch_k,
        len((query_title or "").strip()),
        len((query_description or "").strip()),
        len(query),
        _sha1(query),
        _preview((query_title or "").strip(), 180),
        _preview((query_description or "").strip(), 180),
    )
    logger.info("RAG_EX_WHERE where=%s", where)

    where_no_run = {"type": artifact_type}
    hits_no_run = store.search(
        query=query,
        top_k=fetch_k,
        where=where_no_run,
        min_similarity=None,  # debug: show what's actually in the store
    )
    logger.info("RAG_EX_DEBUG type=%s hits_no_run=%d", artifact_type, len(hits_no_run))

    for h in (hits_no_run[:3] if hits_no_run else []):
        logger.info(
            "RAG_EX_DEBUG sample_meta_keys=%s meta=%s",
            list((h.meta or {}).keys()),
            (h.meta or {}),
        )
        logger.info("RAG_EX_DEBUG hit_preview id=%s len=%d prev=%s", h.id, len(h.text or ""), _preview(h.text or "", 240))
    # ---- DEBUG END (TEMP) ----

    start = time.time()
    hits = store.search(
        query=query,
        top_k=fetch_k,
        where=where,
        min_similarity=None,  # exemplar mode: don't drop top-1 due to threshold
    )
    end = time.time()

    exemplar = ""
    picked: List[MemoryDoc] = []
    if hits:
        picked = [hits[0]]
        exemplar = _trim(getattr(hits[0], "text", "") or "", MAX_EXEMPLAR_CHARS)

    try:
        log_tool_call(
            run_id=run_id or "",
            phase=phase,
            agent="rag",
            tool_type="rag",
            tool_name="rag.exemplar_search",
            start_time=start,
            end_time=end,
            meta={
                "experiment_label": experiment_label,
                "prompt_context_mode": prompt_context_mode,
                "artifact_type": artifact_type,
                "top_k": top_k,
                "n_hits": len(hits),
                "returned": 1 if exemplar else 0,
            },
        )
    except Exception:
        logger.exception("METRICS: failed to log RAG exemplar tool call")

    return exemplar, picked
