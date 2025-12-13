from __future__ import annotations
from typing import Any, Dict, List, Optional, Union, cast, Mapping
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pathlib import Path
import os, json, subprocess, traceback, tempfile, asyncio
from langchain_core.messages import HumanMessage

from app.storage.db import get_db
from app.storage.models import (
    RunORM,
    ProductVisionORM,
    TechnicalSolutionORM,
    EpicORM,
    StoryORM,
    TaskORM,
    AcceptanceORM,
    RunManifestORM,
)
from app.configs.settings import get_settings
from app.agents.coding.coding_agent import CodingAgent
from app.agents.coding.serena_tools import get_serena_tools, close_serena
from app.core.planner import _topo_order

router = APIRouter(prefix="/code", tags=["coding"])

# --- JSON sanitizers ----------------------------------------------------------

def _safe_json(obj: Any, *, max_len: int = 4000) -> Any:
    """Return something JSONable; fallback to repr on weird types (e.g., Send)."""
    try:
        return jsonable_encoder(obj)
    except Exception:
        # try common data-bearing methods
        for attr in ("model_dump", "dict", "__dict__"):
            try:
                val = getattr(obj, attr)
                val = val() if callable(val) else val
                return jsonable_encoder(val)
            except Exception:
                pass
        s = repr(obj)
        return (s[:max_len] + "…") if len(s) > max_len else s

def _only_known_keys(d: Mapping[str, Any]) -> dict:
    """Keep stable, useful fields; stringify everything else."""
    keep = {"ok", "error", "message", "file_changes", "tool_calls", "diff", "edits"}
    out = {}
    for k, v in d.items():
        if k in keep:
            out[k] = _safe_json(v)
    # If nothing matched, keep a generic result
    if not out:
        out["result"] = _safe_json(d)
    return out
# ----------------------------------------------------------------------------- 
def _sse(data: dict) -> bytes:
    # Minimal SSE format: one “data:” line + blank line
    return f"data: {json.dumps(data, default=str)}\n\n".encode("utf-8")

def _workspace_root() -> Path:
    """
    Resolve CODE_WORKSPACES_ROOT to a writable directory.
    Expands ~ and env vars; falls back to /tmp if not writable.
    """
    from app.configs.settings import get_settings

    raw = getattr(get_settings(), "CODE_WORKSPACES_ROOT", "./data/code") or "./data/code"
    # expand ~ and $VARS
    expanded = os.path.expanduser(os.path.expandvars(raw))
    root = Path(expanded).resolve()

    # try to create + write a probe file
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".claire_write_probe"
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        try:
            probe.unlink()
        except FileNotFoundError:
            pass
        return root
    except Exception:
        # safe fallback under /tmp per-user
        fallback = Path(tempfile.gettempdir()) / f"claire-code-{os.getuid()}"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

def _ensure_workspace(run_id: str) -> str:
    """
    Ensure a per-run workspace exists and is minimally initialized.
    """
    root = str(_workspace_root())
    path = os.path.join(root, str(run_id))
    os.makedirs(path, exist_ok=True)

    # Serena metadata
    serena_dir = os.path.join(path, ".serena")
    os.makedirs(serena_dir, exist_ok=True)
    proj_yml = os.path.join(serena_dir, "project.yml")
    if not os.path.exists(proj_yml):
        with open(proj_yml, "w", encoding="utf-8") as f:
            f.write(f"project_name: {run_id}\nlanguage: typescript\n")

    # minimal source stub
    src_dir = os.path.join(path, "src")
    os.makedirs(src_dir, exist_ok=True)
    index_ts = os.path.join(src_dir, "index.ts")
    if not os.path.exists(index_ts):
        with open(index_ts, "w", encoding="utf-8") as f:
            f.write("export function hello(){ console.log('hello'); }\n")

    # init git softly (ignore failures)
    if not os.path.exists(os.path.join(path, ".git")):
        try:
            subprocess.run(["git", "init"], cwd=path, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            with open(os.path.join(path, "README.md"), "a", encoding="utf-8") as f:
                f.write(f"# Workspace for run {run_id}\n")
            subprocess.run(["git", "add", "."], cwd=path, check=True)
            subprocess.run(["git", "commit", "-m", "init workspace"], cwd=path, check=True)
        except Exception:
            pass

    return path

def _as_text(val: Any) -> str:
    if val is None: return ""
    if isinstance(val, str): return val
    if isinstance(val, (list, tuple)): return "\n".join(_as_text(v) for v in val)
    if isinstance(val, dict): return json.dumps(val, ensure_ascii=False, indent=2)
    return str(val)

def _acceptance_text(db: Session, run_id: str, story_id: Union[int, str]) -> str:
    rows = (
        db.query(AcceptanceORM)
        .filter(AcceptanceORM.run_id == run_id, AcceptanceORM.story_id == story_id)
        .order_by(AcceptanceORM.id.asc())
        .all()
    )
    parts = [r.gherkin for r in rows if r.gherkin]
    return "\n\n---\n\n".join(parts)

def _pv_ts_strings(db: Session, run_id: str) -> tuple[str, str]:
    """
    Return compact PV/TS strings while tolerating missing/renamed attributes.
    Avoids Pylance errors by using getattr + sensible defaults.
    """
    pv: Optional[ProductVisionORM] = (
        db.query(ProductVisionORM).filter_by(run_id=run_id).first()
    )
    ts: Optional[TechnicalSolutionORM] = (
        db.query(TechnicalSolutionORM).filter_by(run_id=run_id).first()
    )

    # Pylance-safe attribute access
    pv_features = cast(List[str], getattr(pv, "features", []) or [])
    ts_stack   = cast(List[str], getattr(ts, "stack",   []) or [])
    ts_modules = cast(List[str], getattr(ts, "modules", []) or [])

    # If your schema uses different names, add fallbacks here:
    if not ts_modules:
        ts_modules = cast(List[str], getattr(ts, "components", []) or [])
    if not ts_stack:
        ts_stack = cast(List[str], getattr(ts, "technology_stack", []) or [])

    pvs = " ; ".join(pv_features)
    tss = " ; ".join(ts_stack + ts_modules)
    return pvs, tss

def _epic_title(db: Session, epic_id: Union[str, int]) -> str:
    e: Optional[EpicORM] = db.query(EpicORM).filter_by(id=epic_id).first()
    return (getattr(e, "title", None) or "") if e else ""

def _tasks_for_story(db: Session, run_id: str, story_id: Union[str, int]) -> List[TaskORM]:
    """
    Return tasks for a story ordered deterministically.
    Uses TaskORM.order if present; otherwise falls back to TaskORM.id.
    This avoids Pylance complaining about unknown attributes.
    """
    q = db.query(TaskORM).filter_by(run_id=run_id, story_id=story_id)

    order_attr = getattr(TaskORM, "order", None)  # type: ignore[attr-defined]
    try:
        if order_attr is not None:
            return q.order_by(order_attr.asc()).all()  # type: ignore[attr-defined]
        return q.order_by(TaskORM.id.asc()).all()
    except Exception:
        # If the dialect or attribute fails, always fall back to id
        return q.order_by(TaskORM.id.asc()).all()

def _run_llm_config(db: Session, run_id: str) -> tuple[Optional[str], Optional[str], float]:
    """
    Resolve provider/model/temperature for a run from its manifest,
    falling back to global settings when missing.
    """
    settings = get_settings()
    mf: Optional[RunManifestORM] = (
        db.query(RunManifestORM).filter_by(run_id=run_id).first()
    )
    data = (mf.data or {}) if mf and getattr(mf, "data", None) else {}

    raw_provider = (
        data.get("provider")
        or getattr(settings, "LLM_PROVIDER", None)
        or ""
    )
    provider = raw_provider.strip().lower() or None

    model = data.get("model") or getattr(settings, "LLM_MODEL", None)

    temp_val = data.get("temperature", None)
    try:
        temperature = float(
            temp_val if temp_val is not None else getattr(settings, "TEMPERATURE", 0.2)
        )
    except Exception:
        temperature = float(getattr(settings, "TEMPERATURE", 0.2))

    return provider, model, temperature

@router.get("/runs/{run_id}/tools")
async def list_serena_tools(run_id: str, request: Request):
    project_dir = _ensure_workspace(run_id)
    try:
        tools = await get_serena_tools(request, project_dir=project_dir)
        return jsonable_encoder({"count": len(tools), "tools": [t.name for t in tools]})
    finally:
        try:
            await close_serena(request)
        except Exception:
            pass

@router.post("/runs/{run_id}/story/{story_id}/implement")
async def implement_story(run_id: str, story_id: str, request: Request, db: Session = Depends(get_db)):
    story = db.query(StoryORM).filter_by(run_id=run_id, id=story_id).first()
    if not story:
        raise HTTPException(status_code=404, detail="story not found")

    project_dir = _ensure_workspace(run_id)
    provider, model, temperature = _run_llm_config(db, run_id)
    agent = CodingAgent(model=model, temperature=temperature, provider=provider)

    # Use PV/TS helpers (safe getattr/cast) for type-checker friendliness
    pvs, tss = _pv_ts_strings(db, run_id)
    acc = _acceptance_text(db, run_id, story_id)
    desc = acc or _as_text(story.description)

    # Tasks are now just story-level guidance, not separate agent calls
    tasks_orm = _tasks_for_story(db, run_id, story_id)
    task_titles: List[str] = []
    for t in tasks_orm:
        title = getattr(t, "title", None) or f"Task {getattr(t, 'id', '')}"
        task_titles.append(title)

    try:
        out = await agent.implement_story(
            request=request,
            project_dir=project_dir,
            product_vision=pvs,
            technical_solution=tss,
            epic_title=_epic_title(db, story.epic_id),
            story_title=story.title or "",
            story_desc=desc,
            story_tasks=task_titles,
        )
        from collections.abc import Mapping as _Mapping

        if isinstance(out, _Mapping):
            cleaned = _only_known_keys(out)  # keep useful fields; stringify the rest
        else:
            cleaned = {"result": _safe_json(out)}

        return jsonable_encoder({
            "run_id": run_id,
            "story_id": story_id,
            "tasks": [
                {
                    "id": getattr(t, "id", None),
                    "title": getattr(t, "title", ""),
                    "order": getattr(t, "order", None),
                }
                for t in tasks_orm
            ],
            "result": cleaned,
        })
    except Exception as e:
        return jsonable_encoder({
            "run_id": run_id,
            "story_id": story_id,
            "error": str(e),
            "trace": traceback.format_exc(),
        })


@router.get("/runs/{run_id}/story/{story_id}/implement/stream")
async def implement_story_stream(
    run_id: str,
    story_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    SSE stream of implement progress for a single story.

    IMPORTANT: this is now STORY-LEVEL, not task-by-task.
    We send one Serena agent the full story + task list and stream its events.
    """
    # Validate story from the DB (same as POST /implement)
    story = db.query(StoryORM).filter_by(run_id=run_id, id=story_id).first()
    if not story:
        raise HTTPException(status_code=404, detail="story not found")

    project_dir = _ensure_workspace(run_id)
    provider, model, temperature = _run_llm_config(db, run_id)
    agent = CodingAgent(model=model, temperature=temperature, provider=provider)

    # Shared context (PV/TS/epic/acceptance)
    pvs, tss = _pv_ts_strings(db, run_id)
    epic_title = _epic_title(db, story.epic_id)
    acc = _acceptance_text(db, run_id, story_id)
    story_desc = acc or _as_text(story.description)

    # Still load tasks from DB, but only to build the story_tasks list
    tasks = _tasks_for_story(db, run_id, story_id)
    story_tasks: List[str] = [
        getattr(t, "title", None) or f"Task {getattr(t, 'id', '')}"
        for t in tasks
    ]

    # Same recursion limit we use elsewhere
    settings = get_settings()
    cfg = {"recursion_limit": int(getattr(settings, "CODING_RECURSION_LIMIT", 30))}

    async def gen():
        # Prologue
        yield _sse({
            "type": "stream:start",
            "event": "stream_start",
            "run_id": str(run_id),
            "story_id": story_id,
        })
        yield _sse({
            "type": "story:start",
            "event": "story_begin",
            "run_id": str(run_id),
            "story_id": story_id,
        })

        # Build the exact prompt shape that CodingAgent.implement_story uses
        try:
            runnable = await agent._agent_for(request, project_dir=project_dir)

            tasks_json = json.dumps(story_tasks, indent=2, ensure_ascii=False)
            prompt = (
                f"Product Vision (summary): {pvs}\n"
                f"Technical Solution (stack/modules): {tss}\n"
                f"Epic: {epic_title}\n"
                f"Story: {story.title or ''} — {story_desc}\n"
                f"Story Tasks (with dependencies and priority):\n{tasks_json}\n\n"
                "Implement ALL of these tasks for this story in the fewest possible steps using Serena tools.\n"
                "Respect depends_on and priority_rank when choosing the order of implementation.\n"
                "Do NOT implement tasks from other stories or epics."
            )

            state = {"messages": [HumanMessage(content=prompt)]}

            # Stream raw Serena events, tagged with story_id
            async for ev in runnable.astream_events(cast(Any, state), config=cfg):
                if isinstance(ev, dict):
                    payload = {
                        "type": "event",
                        "story_id": story_id,
                        "name": ev.get("name"),
                        "event": ev.get("event"),
                        "data": _safe_event(ev.get("data")),
                    }
                else:
                    # Fallback for non-dict events
                    payload = {
                        "type": "event",
                        "story_id": story_id,
                        "event": getattr(ev, "event", None),
                        "data": _safe_event(getattr(ev, "data", None)),
                    }

                yield _sse(payload)

            # Normal completion
            yield _sse({
                "type": "story:done",
                "event": "story_end",
                "run_id": str(run_id),
                "story_id": story_id,
                "status": "ok",
            })

        except Exception as e:
            # Error during story execution
            yield _sse({
                "type": "story:error",
                "run_id": str(run_id),
                "story_id": story_id,
                "error": str(e),
            })
        finally:
            # Always try to close Serena for this request
            try:
                await close_serena(request)
            except Exception:
                pass

            # Epilogue
            yield _sse({"type": "stream:done", "run_id": str(run_id), "story_id": story_id})

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)



async def _client_disconnected(request: Request | None) -> bool:
    if not request:
        return False
    try:
        await asyncio.sleep(0)  # allow cancellation to propagate
        return await request.is_disconnected()
    except Exception:
        return False


def _safe_event(data):
    """Make event payload JSON-safe and compact for the UI."""
    try:
        # Drop overly large blobs; trim to essentials that your UI shows
        if isinstance(data, dict):
            d = dict(data)
            # Remove verbose keys if present
            for k in ("messages", "kwargs", "serialized"):
                d.pop(k, None)
            return d
        return data
    except Exception:
        return None

@router.post("/runs/{run_id}/execute")
async def execute_plan(
    run_id: str,
    request: Request,
    epic_id: Optional[str] = Query(None),
    story_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    run = db.query(RunORM).filter_by(id=run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="run not found")

    project_dir = _ensure_workspace(run_id)
    provider, model, temperature = _run_llm_config(db, run_id)
    agent = CodingAgent(model=model, temperature=temperature, provider=provider)
    pvs, tss = _pv_ts_strings(db, run_id)

    # Load all epics/stories for the run
    epics = db.query(EpicORM).filter_by(run_id=run_id).all()
    stories = db.query(StoryORM).filter_by(run_id=run_id).all()

    # Apply filters up-front
    if epic_id is not None:
        epics = [e for e in epics if str(getattr(e, "id")) == str(epic_id)]
        stories = [s for s in stories if str(getattr(s, "epic_id")) == str(epic_id)]
    if story_id is not None:
        stories = [s for s in stories if str(getattr(s, "id")) == str(story_id)]

    # If nothing to do, short-circuit
    if not epics or not stories:
        return jsonable_encoder({"run_id": run_id, "logs": {}})

    # --- Topological order for epics (by depends_on) ---
    epic_order_ids = _topo_order(
        epics,
        get_id=lambda e: str(getattr(e, "id")),
        get_deps=lambda e: [str(d) for d in (getattr(e, "depends_on", []) or [])],
    )
    epic_by_id = {str(getattr(e, "id")): e for e in epics}

    # Group stories by epic
    stories_by_epic: Dict[str, List[StoryORM]] = {}
    for s in stories:
        eid = str(getattr(s, "epic_id"))
        stories_by_epic.setdefault(eid, []).append(s)

    logs: Dict[str, List[Dict[str, Any]]] = {}

    for eid in epic_order_ids:
        e = epic_by_id.get(eid)
        if not e:
            continue

        epic_stories = stories_by_epic.get(eid, [])
        if not epic_stories:
            # no stories for this epic in the filtered set
            continue

        # --- Topological order for stories within this epic ---
        story_order_ids = _topo_order(
            epic_stories,
            get_id=lambda s: str(getattr(s, "id")),
            get_deps=lambda s: [str(d) for d in (getattr(s, "depends_on", []) or [])],
        )
        story_by_id = {str(getattr(s, "id")): s for s in epic_stories}

        for sid in story_order_ids:
            s = story_by_id.get(sid)
            if not s:
                continue

            tasks = _tasks_for_story(db, run_id, s.id)
            acc = _acceptance_text(db, run_id, s.id)
            desc = acc or _as_text(s.description)

            task_titles = [
                getattr(t, "title", None) or f"Task {getattr(t, 'id', '')}"
                for t in tasks
            ]

            try:
                out = await agent.implement_story(
                    request=request,
                    project_dir=project_dir,
                    product_vision=pvs,
                    technical_solution=tss,
                    epic_title=e.title or "",
                    story_title=s.title or "",
                    story_desc=desc,
                    story_tasks=task_titles,
                )

                from collections.abc import Mapping as _Mapping

                if isinstance(out, _Mapping):
                    cleaned = _only_known_keys(out)
                else:
                    cleaned = {"result": _safe_json(out)}

                logs[str(getattr(s, "id"))] = [{
                    "story_id": str(getattr(s, "id")),
                    "epic_id": str(getattr(e, "id")),
                    "task_ids": [str(getattr(t, "id")) for t in tasks],
                    **cleaned,
                }]
            except Exception as e2:
                logs[str(getattr(s, "id"))] = [{
                    "story_id": str(getattr(s, "id")),
                    "epic_id": str(getattr(e, "id")),
                    "error": str(e2),
                    "trace": traceback.format_exc(),
                }]

    return jsonable_encoder({"run_id": run_id, "logs": logs})


