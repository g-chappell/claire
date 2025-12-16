from dataclasses import dataclass, asdict, field
from threading import Lock
from typing import Any, Dict, List, Optional
from pathlib import Path
import os
import json
import time
import logging
from contextvars import ContextVar
from collections import defaultdict

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
    provider_request_id: Optional[str] = None
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

# --------------------------------------------------------------------
# Async context for LLM calls (run_id / phase / agent / story_id)
# --------------------------------------------------------------------

_LLM_CONTEXT: ContextVar[Dict[str, Any]] = ContextVar("LLM_METRICS_CTX", default={})


def set_llm_context(ctx: Optional[Dict[str, Any]]) -> None:
    """
    Set the current LLM metrics context (run_id, phase, agent, story_id, etc.).
    Used by agents/endpoints; read by the LLM callback handler.
    """
    try:
        _LLM_CONTEXT.set(dict(ctx or {}))
    except Exception:
        _LLM_CONTEXT.set({})


def get_llm_context() -> Dict[str, Any]:
    """
    Return the current LLM metrics context, or {} if unset.
    """
    try:
        return _LLM_CONTEXT.get({})
    except LookupError:
        return {}

# Per-million token prices (USD). Adjust here if pricing changes.
# These are *approximate* and used purely for experiment reporting.
_COST_RATES_BY_PROVIDER: Dict[str, Dict[str, float]] = {
    # Anthropic Claude Sonnet 4.5
    "anthropic": {
        "input_per_million": 3.0,
        "output_per_million": 15.0,
    },
    # OpenAI GPT-5.1
    "openai": {
        "input_per_million": 1.25,
        "output_per_million": 10.0,
    },
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


def _estimate_cost(provider: str, input_tokens: int, output_tokens: int) -> float:
    """
    Estimate cost using provider-specific per-million pricing and separate
    input/output token rates.
    """
    cfg = _COST_RATES_BY_PROVIDER.get(provider.lower(), {})
    in_rate = float(cfg.get("input_per_million", 0.0))
    out_rate = float(cfg.get("output_per_million", 0.0))

    cost_in = (input_tokens / 1_000_000.0) * in_rate
    cost_out = (output_tokens / 1_000_000.0) * out_rate
    return cost_in + cost_out


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
    provider_request_id: Optional[str] = None,
) -> None:
    """
    Log a single LLM call at call-level granularity.

    Prefer passing explicit token counts from usage_metadata.
    If they are missing, fall back to crude estimates from text length
    so older models still get *some* accounting.
    """
    try:
        if input_tokens is None:
            input_tokens = _estimate_tokens(input_text or "")
        if output_tokens is None:
            output_tokens = _estimate_tokens(output_text or "")

        input_tokens = int(input_tokens)
        output_tokens = int(output_tokens)
        total_tokens = input_tokens + output_tokens
        cost = _estimate_cost(provider, input_tokens, output_tokens)

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
            provider_request_id=provider_request_id,
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

def _iter_jsonl(path: Path):
    """
    Yield dicts from a JSONL file, skipping blank / bad lines.
    Works for both LLM and tool metrics.
    """
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                logger.warning("METRICS: bad json in %s: %.200s", path, line)

def summarize_by_phase_agent(run_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Aggregate metrics by (phase, agent).

    Returns a list of dicts like:
      {
        "phase": "planning",
        "agent": "tech_writer_tasks",
        "llm_calls": 12,
        "llm_input_tokens": 12345,
        "llm_output_tokens": 6789,
        "llm_total_tokens": 19134,
        "llm_cost_usd": 0.42,
        "llm_duration_s": 123.4,
        "tool_calls": 5,
        "tool_duration_s": 10.2,
      }

    If run_id is provided, only that run is included.
    """
    buckets: Dict[tuple, Dict[str, Any]] = defaultdict(
        lambda: {
            "phase": "",
            "agent": "",
            "llm_calls": 0,
            "llm_input_tokens": 0,
            "llm_output_tokens": 0,
            "llm_total_tokens": 0,
            "llm_cost_usd": 0.0,
            "llm_duration_s": 0.0,
            "tool_calls": 0,
            "tool_duration_s": 0.0,
        }
    )

    # LLM calls
    for row in _iter_jsonl(_LLM_FILE):
        if run_id is not None and row.get("run_id") != run_id:
            continue

        phase = row.get("phase") or "unknown"
        agent = row.get("agent") or "unknown"
        key = (phase, agent)
        b = buckets[key]
        b["phase"] = phase
        b["agent"] = agent

        b["llm_calls"] += 1
        b["llm_input_tokens"] += int(row.get("input_tokens") or 0)
        b["llm_output_tokens"] += int(row.get("output_tokens") or 0)
        b["llm_total_tokens"] += int(row.get("total_tokens") or 0)
        b["llm_cost_usd"] += float(row.get("cost_usd") or 0.0)
        b["llm_duration_s"] += float(row.get("duration_s") or 0.0)

    # Tool calls
    for row in _iter_jsonl(_TOOL_FILE):
        if run_id is not None and row.get("run_id") != run_id:
            continue

        phase = row.get("phase") or "unknown"
        agent = row.get("agent") or "unknown"
        key = (phase, agent)
        b = buckets[key]
        b["phase"] = phase
        b["agent"] = agent

        b["tool_calls"] += 1
        b["tool_duration_s"] += float(row.get("duration_s") or 0.0)

    return sorted(buckets.values(), key=lambda r: (r["phase"], r["agent"]))

def summarize_by_story(run_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Aggregate metrics at story level.

    Returns a list of dicts like:
      {
        "run_id": "...",
        "story_id": "S_123...",
        "phases": ["planning", "coding"],
        "agents": ["vision", "tech_writer_tasks", "coding_agent"],
        "llm_calls": 10,
        "llm_input_tokens": 20000,
        "llm_output_tokens": 4000,
        "llm_total_tokens": 24000,
        "llm_cost_usd": 0.85,
        "llm_duration_s": 300.0,
        "tool_calls": 15,
        "tool_duration_s": 25.5,
      }
    """
    buckets: Dict[tuple, Dict[str, Any]] = defaultdict(
        lambda: {
            "run_id": "",
            "story_id": "",
            "phases": set(),
            "agents": set(),
            "llm_calls": 0,
            "llm_input_tokens": 0,
            "llm_output_tokens": 0,
            "llm_total_tokens": 0,
            "llm_cost_usd": 0.0,
            "llm_duration_s": 0.0,
            "tool_calls": 0,
            "tool_duration_s": 0.0,
        }
    )

    # LLM calls
    for row in _iter_jsonl(_LLM_FILE):
        if run_id is not None and row.get("run_id") != run_id:
            continue

        rid = row.get("run_id") or "unknown"
        sid = row.get("story_id") or "unknown"
        key = (rid, sid)
        b = buckets[key]
        b["run_id"] = rid
        b["story_id"] = sid

        phase = row.get("phase") or "unknown"
        agent = row.get("agent") or "unknown"
        b["phases"].add(phase)
        b["agents"].add(agent)

        b["llm_calls"] += 1
        b["llm_input_tokens"] += int(row.get("input_tokens") or 0)
        b["llm_output_tokens"] += int(row.get("output_tokens") or 0)
        b["llm_total_tokens"] += int(row.get("total_tokens") or 0)
        b["llm_cost_usd"] += float(row.get("cost_usd") or 0.0)
        b["llm_duration_s"] += float(row.get("duration_s") or 0.0)

    # Tool calls
    for row in _iter_jsonl(_TOOL_FILE):
        if run_id is not None and row.get("run_id") != run_id:
            continue

        rid = row.get("run_id") or "unknown"
        sid = row.get("story_id") or "unknown"
        key = (rid, sid)
        b = buckets[key]
        b["run_id"] = rid
        b["story_id"] = sid

        phase = row.get("phase") or "unknown"
        agent = row.get("agent") or "unknown"
        b["phases"].add(phase)
        b["agents"].add(agent)

        b["tool_calls"] += 1
        b["tool_duration_s"] += float(row.get("duration_s") or 0.0)

    # Convert sets → sorted lists for JSON/pandas friendliness
    out: List[Dict[str, Any]] = []
    for (rid, sid), b in buckets.items():
        b["phases"] = sorted(b["phases"])
        b["agents"] = sorted(b["agents"])
        out.append(b)

    return sorted(out, key=lambda r: (r["run_id"], r["story_id"]))
