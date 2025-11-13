from __future__ import annotations
from typing import Any, Dict, List, Optional, Union, cast
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session
from pathlib import Path
import os, json, subprocess, traceback, tempfile

from app.storage.db import get_db
from app.storage.models import (
    RunORM, ProductVisionORM, TechnicalSolutionORM, EpicORM, StoryORM, TaskORM, AcceptanceORM
)
from app.configs.settings import get_settings
from app.agents.coding.coding_agent import CodingAgent
from app.agents.coding.serena_tools import get_serena_tools, close_serena

router = APIRouter(prefix="/code", tags=["coding"])

# --- JSON sanitizers ----------------------------------------------------------
from typing import Any, Mapping
from fastapi.encoders import jsonable_encoder

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
    agent = CodingAgent()

    # Use PV/TS helpers (safe getattr/cast) for type-checker friendliness
    pvs, tss = _pv_ts_strings(db, run_id)
    acc = _acceptance_text(db, run_id, story_id)
    desc = acc or _as_text(story.description)

    # Strict 1-by-1: tasks ordered via helper (uses .order if present, else .id)
    tasks = _tasks_for_story(db, run_id, story_id)

    results: List[Dict[str, Any]] = []
    for t in tasks:
        try:
            out = await agent.implement_task(
                request=request,
                project_dir=project_dir,
                product_vision=pvs,
                technical_solution=tss,
                epic_title=_epic_title(db, story.epic_id),
                story_title=story.title or "",
                story_desc=desc,
                task_title=t.title or "",
            )
            from collections.abc import Mapping as _Mapping

            task_id = getattr(t, "id", None) or getattr(t, "task_id", None)

            if isinstance(out, _Mapping):
                cleaned = _only_known_keys(out)  # keep useful fields; stringify the rest
            else:
                cleaned = {"result": _safe_json(out)}

            results.append({"task_id": task_id, **cleaned})
        except Exception as e:
            results.append({"task_id": t.id, "error": str(e), "trace": traceback.format_exc()})

    return jsonable_encoder({"run_id": run_id, "story_id": story_id, "results": results})


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
    agent = CodingAgent()
    pvs, tss = _pv_ts_strings(db, run_id)

    def ekey(e: EpicORM) -> tuple[int, str]:
        name = (e.title or "").lower()
        if any(k in name for k in ["scaffold", "bootstrap", "baseline", "foundation"]): return (0, name)
        if any(k in name for k in ["core", "auth", "routing", "persistence"]): return (1, name)
        return (2, name)

    epics = db.query(EpicORM).filter_by(run_id=run_id).all()
    stories = db.query(StoryORM).filter_by(run_id=run_id).all()
    if epic_id:
        epics = [e for e in epics if e.id == epic_id]
    epics = sorted(epics, key=ekey)
    if story_id:
        stories = [s for s in stories if s.id == story_id]

    logs: Dict[str, List[Dict[str, Any]]] = {}

    for e in epics:
        s_list = sorted(
            [s for s in stories if s.epic_id == e.id],
            key=lambda s: (s.priority_rank or 9999, s.id),
        )
        for s in s_list:
            # Use the helper instead of TaskORM.order directly
            tasks = _tasks_for_story(db, run_id, s.id)
            story_logs: List[Dict[str, Any]] = []
            acc = _acceptance_text(db, run_id, s.id)
            desc = acc or _as_text(s.description)
            for t in tasks:
                try:
                    out = await agent.implement_task(
                        request=request,
                        project_dir=project_dir,
                        product_vision=pvs,
                        technical_solution=tss,
                        epic_title=e.title or "",
                        story_title=s.title or "",
                        story_desc=desc,
                        task_title=t.title or "",
                    )

                    from collections.abc import Mapping as _Mapping
                    task_id = getattr(t, "id", None) or getattr(t, "task_id", None)

                    if isinstance(out, _Mapping):
                        cleaned = _only_known_keys(out)
                    else:
                        cleaned = {"result": _safe_json(out)}

                    story_logs.append({"task_id": task_id, **cleaned})
                except Exception as e2:
                    story_logs.append({"task_id": getattr(t, "id", None), "error": str(e2), "trace": traceback.format_exc()})
                logs[s.id] = story_logs

    return jsonable_encoder({"run_id": run_id, "logs": logs})

