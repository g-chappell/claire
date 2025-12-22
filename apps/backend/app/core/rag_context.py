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

# Hard floor to prevent weak/irrelevant matches polluting prompts
MIN_MATCH_SIMILARITY_FLOOR = 0.35

def _safe_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None

def _hit_sim(h: MemoryDoc) -> Optional[float]:
    meta = getattr(h, "meta", None) or {}
    # ChromaMemoryStore sets debug_similarity as a string.
    return _safe_float(meta.get("debug_similarity") or meta.get("similarity") or meta.get("score"))

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
        "RAG_CTX_SEARCH phase=%s run=%s types=%s top_k=%s fetch_k=%s min_sim=%s q_len=%d q_sha1=%s",
        phase,
        run_id,
        type_list,
        top_k or settings.RAG_TOP_K,
        fetch_k,
        settings.RAG_MIN_SIMILARITY,
        len(query),
        _sha1(query),
    )

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("RAG_CTX_QUERY_PREVIEW q_prev=%s", _preview(query, 240))
        logger.debug("RAG_CTX_WHERE where=%s", where)

    # Apply a hard floor so weak matches never enter prompts.
    min_match = max(float(getattr(settings, "RAG_MIN_SIMILARITY", 0.0) or 0.0), MIN_MATCH_SIMILARITY_FLOOR)

    start = time.time()
    candidates = store.search(
        query=query,
        top_k=fetch_k,
        where=where,
        # IMPORTANT: fetch without filtering so we can log best score even if rejected
        min_similarity=None,
    )

    # Exclude current run docs (post-filter for store compatibility)
    if run_id:
        candidates = [h for h in candidates if str((h.meta or {}).get("run_id", "")) != str(run_id)]

    # Apply similarity threshold filtering ourselves
    hits: List[MemoryDoc] = []
    best_sim: Optional[float] = None
    for h in candidates:
        sim = _hit_sim(h)
        if sim is not None:
            if best_sim is None or sim > best_sim:
                best_sim = sim
            if sim < min_match:
                continue
        hits.append(h)

    end = time.time()

    elapsed_ms = int((end - start) * 1000)
    logger.info(
        "RAG_CTX_RESULT phase=%s run=%s candidates=%d hits=%d best_sim=%s min_match=%s elapsed_ms=%d",
        phase,
        run_id,
        len(candidates),
        len(hits),
        f"{best_sim:.4f}" if best_sim is not None else "n/a",
        f"{min_match:.2f}",
        elapsed_ms,
    )

    if logger.isEnabledFor(logging.DEBUG):
        for h in hits[:5]:
            meta = h.meta or {}
            label = meta.get("req_title") or meta.get("title") or ""
            logger.debug(
                "RAG_CTX_HIT type=%s title=%s id=%s sim=%s dist=%s",
                meta.get("type"),
                label,
                h.id,
                meta.get("debug_similarity"),
                meta.get("debug_distance"),
            )
            logger.debug("RAG_CTX_HIT_PREVIEW len=%d prev=%s", len(h.text or ""), _preview(h.text or "", 240))

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
                    "n_candidates": len(candidates) if "candidates" in locals() else 0,
                    "n_hits": 0,
                    "min_match_similarity": min_match if "min_match" in locals() else None,
                    "best_similarity": best_sim if "best_sim" in locals() else None,
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
                "n_candidates": len(candidates),
                "n_hits": len(hits),
                "min_match_similarity": min_match,
                "best_similarity": best_sim,
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
    # Do NOT use $ne in where; filter post-retrieval for compatibility

    fetch_k = max(1, top_k) * max(1, settings.RAG_OVERFETCH)

    logger.info(
        "RAG_EX_SEARCH phase=%s run=%s type=%s top_k=%s fetch_k=%s min_sim=%s q_len=%d q_sha1=%s",
        phase,
        run_id,
        artifact_type,
        top_k,
        fetch_k,
        settings.RAG_MIN_SIMILARITY,
        len(query),
        _sha1(query),
    )

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("RAG_EX_QUERY_PREVIEW title_prev=%s", _preview((query_title or "").strip(), 180))
        logger.debug("RAG_EX_QUERY_PREVIEW desc_prev=%s", _preview((query_description or "").strip(), 180))
        logger.debug("RAG_EX_WHERE where=%s", where)

    min_match = max(float(getattr(settings, "RAG_MIN_SIMILARITY", 0.0) or 0.0), MIN_MATCH_SIMILARITY_FLOOR)

    start = time.time()
    candidates = store.search(
        query=query,
        top_k=fetch_k,
        where=where,
        # IMPORTANT: do not pre-filter; we want to log best score even when rejected
        min_similarity=None,
    )
    if run_id:
        candidates = [h for h in candidates if str((h.meta or {}).get("run_id", "")) != str(run_id)]
    end = time.time()

    exemplar = ""
    picked: List[MemoryDoc] = []

    best_sim: Optional[float] = None
    best_id: str = ""
    best_title: str = ""

    if candidates:
        h0 = candidates[0]
        sim0 = _hit_sim(h0)
        best_sim = sim0
        best_id = getattr(h0, "id", "") or ""
        best_title = str((getattr(h0, "meta", None) or {}).get("title") or "")

        # Reject weak match
        if sim0 is None or sim0 >= min_match:
            picked = [h0]
            exemplar = _trim(getattr(h0, "text", "") or "", MAX_EXEMPLAR_CHARS)

        logger.info(
        "RAG_EX_PICK phase=%s run=%s type=%s found=%s best_sim=%s min_match=%s best_id=%s best_title=%s candidates=%d",
        phase,
        run_id,
        artifact_type,
        bool(exemplar),
        f"{best_sim:.4f}" if best_sim is not None else "n/a",
        f"{min_match:.2f}",
        best_id or "n/a",
        (best_title[:120] + "…") if len(best_title) > 120 else (best_title or "n/a"),
        len(candidates),
    )

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
                "n_candidates": len(candidates),
                "n_hits": len(candidates),  # raw returned by store (pre-threshold)
                "min_match_similarity": min_match,
                "best_similarity": best_sim,
                "returned": 1 if exemplar else 0,
            },
        )
    except Exception:
        logger.exception("METRICS: failed to log RAG exemplar tool call")

    return exemplar, picked
