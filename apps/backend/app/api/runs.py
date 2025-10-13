from __future__ import annotations
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.configs.settings import get_settings
from app.core.models import RunCreate, RunManifest
from app.storage.db import get_db
from app.storage.models import RunORM, RunManifestORM, RequirementORM


router = APIRouter()
settings = get_settings()

@router.post("/runs")
def create_run(payload: RunCreate, db: Session = Depends(get_db)):
    run_id = str(uuid.uuid4())
    run = RunORM(id=run_id, status="DRAFT")
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
        constraints=payload.constraints,
        priority=payload.priority,
        non_functionals=payload.non_functionals,
    )
    db.add(req)


    db.commit()


    return {
        "run_id": run_id,
        "manifest": RunManifest(
            run_id=run_id,
            model=settings.LLM_MODEL,
            provider=settings.LLM_PROVIDER,
            temperature=settings.TEMPERATURE,
            context_snapshot_id=manifest.data["context_snapshot_id"],
        ),
        "requirement_id": req.id,
        "status": run.status,
    }

@router.get("/runs/{run_id}")
def get_run(run_id: str, db: Session = Depends(get_db)):
    run = db.get(RunORM, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    manifest = db.get(RunManifestORM, run_id)
    req = (
        db.query(RequirementORM)
        .filter(RequirementORM.run_id == run_id)
        .order_by(RequirementORM.id.asc())
        .first()
    )
    return {
        "run": {"id": run.id, "status": run.status, "started_at": run.started_at, "finished_at": run.finished_at},
        "manifest": manifest.data if manifest else None,
        "requirement": {
        "id": req.id,
        "title": req.title,
        "description": req.description,
        "constraints": req.constraints,
        "priority": req.priority,
        "non_functionals": req.non_functionals,
        }
        if req
        else None,
    }