from __future__ import annotations
import uuid
import logging
from typing import Literal, Optional, cast
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.configs.settings import get_settings  # if Settings class is exported, you can: from app.configs.settings import Settings
from app.core.models import RunCreate, RunManifest
from app.storage.db import get_db
from app.storage.models import (
    RunORM,
    RunManifestORM,
    RequirementORM,
)
from app.core.runs import hard_delete_run, clear_plan_artifacts

logger = logging.getLogger(__name__)
router = APIRouter()

# If your settings module exposes a Settings class, uncomment and annotate:
# from app.configs.settings import Settings
# settings: Settings = get_settings()
settings = get_settings()

@router.post("/runs")
def create_run(payload: RunCreate, db: Session = Depends(get_db)):
    """Create a run + manifest + initial requirement row."""
    run_id = str(uuid.uuid4())

    payload_title = getattr(payload, "run_title", None) or \
                    getattr(payload, "title", None) or \
                    getattr(payload, "requirement_title", None) or ""

    run = RunORM(id=run_id, status="DRAFT", title=(payload_title or "")[:200])  # <-- set title

    run = RunORM(id=run_id, status="DRAFT", title=(payload_title or "")[:200])
    db.add(run)

    # ---- Resolve experiment knobs: payload value → settings default ----
    exp_label = (
        payload.experiment_label
        if getattr(payload, "experiment_label", None)
        else getattr(settings, "EXPERIMENT_LABEL", None)
    )

    mode = (
        payload.prompt_context_mode
        if getattr(payload, "prompt_context_mode", None)
        else getattr(settings, "PROMPT_CONTEXT_MODE", "structured")
    ) or "structured"

    # use_rag can legitimately be False, so we need a None check
    payload_use_rag = getattr(payload, "use_rag", None)
    if payload_use_rag is None:
        rag_flag = getattr(settings, "USE_RAG", True)
    else:
        rag_flag = bool(payload_use_rag)

    # NEW: provider snapshot – prefer per-run if supplied
    raw_provider = getattr(payload, "llm_provider", None)
    if raw_provider:
        provider = raw_provider.strip().lower()
    else:
        provider = getattr(settings, "LLM_PROVIDER", None)

    # NEW: pick model based on provider snapshot
    # Env layout:
    #   ANTHROPIC_MODEL = e.g. "claude-sonnet-4-5-20250929"
    #   OPENAI_MODEL    = e.g. "gpt-5.1-2025-11-13"
    #
    # LLM_MODEL (if present) acts as a generic fallback.
    if provider == "openai":
        model = getattr(settings, "OPENAI_MODEL", None) or getattr(settings, "LLM_MODEL", None)
    elif provider == "anthropic":
        model = getattr(settings, "ANTHROPIC_MODEL", None) or getattr(settings, "LLM_MODEL", None)
    else:
        # Fallback if provider is missing/unknown
        model = getattr(settings, "LLM_MODEL", None)

    # Final safety net: if still missing, set a sensible default
    if not model:
        if provider == "openai":
            model = "gpt-5.1-2025-11-13"
        else:
            model = "claude-sonnet-4-5-20250929" 

    manifest = RunManifestORM(
        run_id=run_id,
        data={
            "model": model,
            "provider": provider,
            "temperature": settings.TEMPERATURE,
            "context_snapshot_id": str(uuid.uuid4()),
            # --- experiment snapshot at creation time ---
            "experiment_label": exp_label,
            "prompt_context_mode": mode,
            "use_rag": rag_flag,
        },
    )
    db.add(manifest)

    req = RequirementORM(
        id=f"{run_id[:8]}-REQ",
        run_id=run_id,
        title=payload.requirement_title,
        description=payload.requirement_description,
        constraints=payload.constraints or [],
        priority=payload.priority or "Should",
        non_functionals=payload.non_functionals or [],
    )
    db.add(req)

    db.commit()

    # Re-fetch manifest via filter_by to avoid PK assumptions
    mf: Optional[RunManifestORM] = (
        db.query(RunManifestORM).filter_by(run_id=run_id).first()
    )
    manifest_data: dict = {}
    if mf and getattr(mf, "data", None):
        manifest_data = cast(dict, mf.data)

    return {
        "run_id": run_id,
        "manifest": RunManifest(
            run_id=run_id,
            model=manifest_data.get("model", settings.LLM_MODEL),
            provider=manifest_data.get("provider", settings.LLM_PROVIDER),
            temperature=manifest_data.get("temperature", settings.TEMPERATURE),
            context_snapshot_id=manifest_data.get("context_snapshot_id", ""),
            experiment_label=manifest_data.get(
                "experiment_label",
                getattr(settings, "EXPERIMENT_LABEL", None),
            ),
            prompt_context_mode=manifest_data.get(
                "prompt_context_mode",
                getattr(settings, "PROMPT_CONTEXT_MODE", "structured"),
            ),
            use_rag=manifest_data.get(
                "use_rag",
                getattr(settings, "USE_RAG", True),
            ),
        ),
        "requirement_id": req.id,
        "status": cast(str, run.status),
    }


@router.get("/runs/{run_id}")
def get_run(run_id: str, db: Session = Depends(get_db)):
    """Return run + manifest + first requirement snapshot."""
    run: Optional[RunORM] = db.query(RunORM).filter_by(id=run_id).first()
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    manifest: Optional[RunManifestORM] = (
        db.query(RunManifestORM).filter_by(run_id=run_id).first()
    )
    req: Optional[RequirementORM] = (
        db.query(RequirementORM)
        .filter(RequirementORM.run_id == run_id)
        .order_by(RequirementORM.id.asc())
        .first()
    )

    run_out = {
        "id": run.id,
        "title": getattr(run, "title", None),   # <-- include title
        "status": run.status,
        "started_at": getattr(run, "started_at", None),
        "finished_at": getattr(run, "finished_at", None),
    }

    manifest_out = manifest.data if (manifest and getattr(manifest, "data", None)) else None

    requirement_out = (
        None
        if req is None
        else {
            "id": req.id,
            "title": req.title,
            "description": req.description,
            "constraints": req.constraints or [],
            "priority": req.priority or "Should",
            "non_functionals": req.non_functionals or [],
        }
    )

    return {"run": run_out, "manifest": manifest_out, "requirement": requirement_out}


@router.delete("/runs/{run_id}")
def delete_run_api(run_id: str, db: Session = Depends(get_db)):
    """Hard delete a run + all related artifacts."""
    try:
        counts = hard_delete_run(db, run_id)
        return {"ok": True, "deleted": counts}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception:
        logger.exception("delete run failed")
        raise HTTPException(status_code=500, detail="failed to delete run")
    
class GateUpdate(BaseModel):
    vision_solution_status: Literal["approved", "draft", "rejected"]

@router.get("/runs/{run_id}/gate")
def get_gate(run_id: str, db: Session = Depends(get_db)):
    manifest: Optional[RunManifestORM] = (
        db.query(RunManifestORM).filter_by(run_id=run_id).first()
    )
    status = (manifest.data or {}).get("vision_solution_status") if manifest else None
    return {"run_id": run_id, "vision_solution_status": status}

@router.patch("/runs/{run_id}/gate")
def update_gate(run_id: str, body: GateUpdate, db: Session = Depends(get_db)):
    manifest: Optional[RunManifestORM] = (
        db.query(RunManifestORM).filter_by(run_id=run_id).first()
    )
    if manifest is None:
        manifest = RunManifestORM(run_id=run_id, data={})
        db.add(manifest)

    data = dict(manifest.data or {})
    data["vision_solution_status"] = body.vision_solution_status
    manifest.data = data

    db.commit()
    db.refresh(manifest)
    return {"run_id": run_id, "vision_solution_status": manifest.data.get("vision_solution_status")}

@router.delete("/runs/{run_id}/plan")
def reset_plan(run_id: str, db: Session = Depends(get_db)):
    counts = clear_plan_artifacts(db, run_id)
    return {"ok": True, "deleted": counts, "kept": ["product_vision", "technical_solution"]}