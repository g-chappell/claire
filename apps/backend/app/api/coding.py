# apps/backend/app/api/coding.py
from __future__ import annotations
from typing import List, Any, Union
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from app.storage.db import get_db
from app.storage.models import StoryORM, RunORM, AcceptanceORM
from app.agents.coding.coding_agent import CodingAgent
import json, os, subprocess
from app.configs.settings import get_settings
import traceback
from fastapi.responses import JSONResponse
from app.agents.coding.serena_tools import get_serena_tools, close_serena
from pathlib import Path

router = APIRouter(prefix="/code", tags=["coding"])

def _err(e: Exception) -> JSONResponse:
    return JSONResponse(
        {"error": str(e), "trace": traceback.format_exc()}, status_code=500
    )

def _workspace_root() -> Path:
    # Root folder where per-run workspaces live
    return Path(get_settings().SERENA_PROJECT_DIR).resolve()

def _project_dir_for_run(run_id: str) -> str:
    # Pure path calculation; no I/O
    return str(_workspace_root() / run_id)

def _ensure_workspace(run_id: str) -> str:
    """Create a per-run workspace folder and init git on first use."""
    settings = get_settings()
    root = os.path.abspath(getattr(settings, "CODE_WORKSPACES_ROOT", "./data/code"))
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, str(run_id))
    os.makedirs(path, exist_ok=True)
    # Seed minimal project so Serena can activate (either source file or project.yml)
    serena_dir = os.path.join(path, ".serena")
    os.makedirs(serena_dir, exist_ok=True)
    proj_yml = os.path.join(serena_dir, "project.yml")
    if not os.path.exists(proj_yml):
        # pick your preferred language: "typescript" or "python"
        with open(proj_yml, "w", encoding="utf-8") as f:
            f.write(f"project_name: {run_id}\nlanguage: typescript\n")

    # minimal source so indexers don’t complain
    src_dir = os.path.join(path, "src")
    os.makedirs(src_dir, exist_ok=True)
    index_ts = os.path.join(src_dir, "index.ts")
    if not os.path.exists(index_ts):
        with open(index_ts, "w", encoding="utf-8") as f:
            f.write("export function hello(){ console.log('hello'); }\n")

    # git init once
    if not os.path.exists(os.path.join(path, ".git")):
        try:
            subprocess.run(["git", "init"], cwd=path, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            # Small placeholder so the repo isn't empty
            with open(os.path.join(path, "README.md"), "a", encoding="utf-8") as f:
                f.write(f"# Workspace for run {run_id}\n")
            # track seeded files
            subprocess.run(["git", "add", "."], cwd=path, check=True)
            subprocess.run(["git", "commit", "-m", "init workspace"], cwd=path, check=True)
        except Exception:
            # If git isn't available, it's fine; Serena can still write files.
            pass
    return path


def _as_text(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, (list, tuple)):
        return "\n".join(_as_text(v) for v in val)  # flatten nested lists safely
    if isinstance(val, dict):
        return json.dumps(val, ensure_ascii=False, indent=2)
    return str(val)

def _get_stories(db: Session, run_id: str) -> List[StoryORM]:
    return (
        db.query(StoryORM)
        .filter(StoryORM.run_id == run_id)
        .order_by(StoryORM.priority_rank.asc(), StoryORM.id.asc())
        .all()
    )

def _get_acceptance_text(db: Session, run_id: str, story_id: Union[int, str]) -> str:
    """Gather all AcceptanceORM.gherkin rows for a story into a single string."""
    rows = (
        db.query(AcceptanceORM)
        .filter(AcceptanceORM.run_id == run_id, AcceptanceORM.story_id == story_id)
        .order_by(AcceptanceORM.id.asc())
        .all()
    )
    parts = [r.gherkin for r in rows if r.gherkin]
    return "\n\n---\n\n".join(parts)

@router.post("/runs/{run_id}/story/{story_id}/implement")
async def implement_single_story(run_id: str, story_id: str, request: Request, db: Session = Depends(get_db)):
    story = db.query(StoryORM).filter(StoryORM.run_id == run_id, StoryORM.id == story_id).first()
    if not story:
        raise HTTPException(status_code=404, detail="story not found")
    project_dir = _ensure_workspace(run_id)
    agent = CodingAgent()
    acc = _get_acceptance_text(db, run_id, story_id)
    desc = acc or _as_text(story.description)
    try:
        out = await agent.implement_story(
            request, story.title, desc, project_dir=project_dir
        )
        return {"run_id": run_id, "story_id": story_id, **out}
    except HTTPException:
        raise
    except Exception as e:
        return _err(e)

@router.post("/runs/{run_id}/implement-all")
async def implement_all_stories(run_id: str, request: Request, db: Session = Depends(get_db)):
    run = db.query(RunORM).filter(RunORM.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="run not found")

    stories = _get_stories(db, run_id)
    project_dir = _ensure_workspace(run_id)
    agent = CodingAgent()
    
    results = []
    for s in stories:
        acc = _get_acceptance_text(db, run_id, s.id)
        desc = acc or _as_text(s.description)
        try:
            out = await agent.implement_story(
                request, s.title, desc, project_dir=project_dir
            )
            results.append({"story_id": s.id, "title": s.title, **out})
        except HTTPException:
            raise
        except Exception as e:
            results.append({
                "story_id": s.id,
                "title": s.title,
                "error": str(e),
                "trace": traceback.format_exc(),
            })

    return {"run_id": run_id, "results": results}

@router.get("/runs/{run_id}/tools")
async def list_serena_tools(run_id: str, request: Request):
    # ensure the folder exists and has minimal files + .serena/project.yml
    project_dir = _ensure_workspace(run_id)
    try:
        tools = await get_serena_tools(request, project_dir=project_dir)
        return {"count": len(tools), "tools": [t.name for t in tools]}
    finally:
        # Make sure the MCP session is torn down here (we only needed it to list)
        try:
            await close_serena(request)
        except Exception:
            pass