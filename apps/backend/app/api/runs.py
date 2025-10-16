from __future__ import annotations
import uuid
import logging
from typing import Optional, cast

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
from app.core.runs import hard_delete_run

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

    db.add(run)

    manifest = RunManifestORM(
        run_id=run_id,
        data={
            "model": settings.LLM_MODEL,
            "provider": settings.LLM_PROVIDER,
            "temperature": settings.TEMPERATURE,
            "context_snapshot_id": str(uuid.uuid4()),
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
    ctx_id = ""
    if mf and getattr(mf, "data", None):
        ctx_id = cast(dict, mf.data).get("context_snapshot_id", "")

    return {
        "run_id": run_id,
        "manifest": RunManifest(
            run_id=run_id,
            model=settings.LLM_MODEL,
            provider=settings.LLM_PROVIDER,
            temperature=settings.TEMPERATURE,
            context_snapshot_id=ctx_id,
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