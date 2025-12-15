from dataclasses import dataclass, asdict, field
from threading import Lock
from typing import Any, Dict, List, Optional
from pathlib import Path
import os
import json
import time
import logging

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------
# Storage locations (in-memory + JSONL on disk)
# --------------------------------------------------------------------

def _metrics_dir() -> Path:
    """
    Resolve metrics directory. Uses CLAIRE_METRICS_DIR if set,
    otherwise ./data/metrics relative to the backend working dir.
    Falls back to /tmp/claire-metrics if needed.
    """
    base = os.getenv("CLAIRE_METRICS_DIR", "./data/metrics")
    try:
        p = Path(base).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p
    except Exception:
        fallback = Path("/tmp/claire-metrics")
        try:
            fallback.mkdir(parents=True, exist_ok=True)
        except Exception:
            # Last resort: current working directory
            return Path(".").resolve()
        return fallback

_METRICS_DIR = _metrics_dir()
_LLM_FILE = _METRICS_DIR / "llm_calls.jsonl"
_TOOL_FILE = _METRICS_DIR / "tool_calls.jsonl"


# --------------------------------------------------------------------
# Data structures
# --------------------------------------------------------------------

@dataclass
class LLMCallRecord:
    ts: float
    run_id: str
    phase: str              # e.g. "planning", "coding"
    agent: str              # e.g. "vision", "architect", "requirements_analyst"
    provider: str           # "anthropic" | "openai" | ...
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float
    duration_s: float
    story_id: Optional[str] = None
    tool_name: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCallRecord:
    ts: float
    run_id: str
    phase: str              # "planning", "coding", etc.
    agent: str              # which agent invoked the tool
    tool_type: str          # e.g. "rag", "fs", "serena"
    tool_name: str          # e.g. "rag.search", "find_symbol"
    duration_s: float
    story_id: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)


_LLM_CALLS: List[LLMCallRecord] = []
_TOOL_CALLS: List[ToolCallRecord] = []
_LOCK = Lock()

# Very rough per-1k token costs in USD – tweak as you like
_COST_PER_1K_BY_PROVIDER: Dict[str, float] = {
    "anthropic": 3.0,
    "openai": 2.0,
}


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------

def _estimate_tokens(text: str) -> int:
    """
    Crude but consistent token estimate: ~4 chars/token.
    Good enough for relative cost comparisons across runs.
    """
    if not text:
        return 0
    return max(1, len(text) // 4)


def _estimate_cost(provider: str, total_tokens: int) -> float:
    rate = _COST_PER_1K_BY_PROVIDER.get(provider.lower(), 2.0)
    return (total_tokens / 1000.0) * rate


# --------------------------------------------------------------------
# Public logging API
# --------------------------------------------------------------------

def log_llm_call(
    *,
    run_id: str,
    phase: str,
    agent: str,
    provider: str,
    model: str,
    start_time: float,
    end_time: float,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    input_text: Optional[str] = None,
    output_text: Optional[str] = None,
    story_id: Optional[str] = None,
    tool_name: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Log a single LLM call at call-level granularity.

    Either pass explicit token counts OR rely on the (rough) estimates from
    input_text/output_text. This is per-call; you can aggregate by run/phase
    offline for the dissertation tables.
    """
    try:
        if input_tokens is None:
            input_tokens = _estimate_tokens(input_text or "")
        if output_tokens is None:
            output_tokens = _estimate_tokens(output_text or "")

        input_tokens = int(input_tokens)
        output_tokens = int(output_tokens)
        total_tokens = input_tokens + output_tokens
        cost = _estimate_cost(provider, total_tokens)

        rec = LLMCallRecord(
            ts=time.time(),
            run_id=run_id,
            phase=phase,
            agent=agent,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cost_usd=cost,
            duration_s=max(0.0, end_time - start_time),
            story_id=story_id,
            tool_name=tool_name,
            metadata=metadata or {},
        )

        with _LOCK:
            _LLM_CALLS.append(rec)
            try:
                with _LLM_FILE.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(asdict(rec), default=str) + "\n")
            except Exception:
                logger.exception("METRICS: failed to persist LLM call to file")
    except Exception:
        # Metrics must never break the main app
        logger.exception("METRICS: failed to log LLM call")


def log_tool_call(
    *,
    run_id: str,
    phase: str,
    agent: str,
    tool_type: str,
    tool_name: str,
    start_time: float,
    end_time: float,
    story_id: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Log a tool call (RAG, Serena, etc). Same story: per-call; aggregate later.
    """
    try:
        rec = ToolCallRecord(
            ts=time.time(),
            run_id=run_id,
            phase=phase,
            agent=agent,
            tool_type=tool_type,
            tool_name=tool_name,
            duration_s=max(0.0, end_time - start_time),
            story_id=story_id,
            meta=meta or {},
        )
        with _LOCK:
            _TOOL_CALLS.append(rec)
            try:
                with _TOOL_FILE.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(asdict(rec), default=str) + "\n")
            except Exception:
                logger.exception("METRICS: failed to persist tool call to file")
    except Exception:
        logger.exception("METRICS: failed to log tool call")


# --------------------------------------------------------------------
# Introspection helpers (for later export/inspection)
# --------------------------------------------------------------------

def get_llm_calls(run_id: Optional[str] = None) -> List[Dict[str, Any]]:
    with _LOCK:
        rows = list(_LLM_CALLS)
    if run_id is not None:
        rows = [r for r in rows if r.run_id == run_id]
    return [asdict(r) for r in rows]


def get_tool_calls(run_id: Optional[str] = None) -> List[Dict[str, Any]]:
    with _LOCK:
        rows = list(_TOOL_CALLS)
    if run_id is not None:
        rows = [r for r in rows if r.run_id == run_id]
    return [asdict(r) for r in rows]


def reset_metrics() -> None:
    with _LOCK:
        _LLM_CALLS.clear()
        _TOOL_CALLS.clear()
