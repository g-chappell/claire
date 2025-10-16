# app/api/runs_qol.py
from __future__ import annotations
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.storage.db import get_db
from app.storage.models import RunORM, EpicORM, StoryORM
from app.core.planner import read_plan

router = APIRouter()

# ---- Schemas (lightweight, API-only) ----
from pydantic import BaseModel

class RunSummary(BaseModel):
    id: str
    title: Optional[str] = None
    status: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

class EpicOut(BaseModel):
    id: str
    run_id: str
    title: str
    description: str = ""
    priority_rank: int

class StoryOut(BaseModel):
    id: str
    run_id: str
    epic_id: str
    title: str
    description: str = ""
    priority_rank: int

def _has_attr(model, name: str) -> bool:
    return hasattr(model, name) and name in model.__table__.columns

# ---- QoL routes ----

@router.get("/runs", response_model=List[RunSummary])
def list_runs(db: Session = Depends(get_db)):
    q = db.query(RunORM)
    # Prefer created_at desc if present; fall back to id desc
    if _has_attr(RunORM, "started_at"):
        q = q.order_by(RunORM.started_at.desc())
    else:
        q = q.order_by(RunORM.id.desc())
    rows = q.all()
    return [
        RunSummary(
            id=r.id,
            title=getattr(r, "title", None),
            status=getattr(r, "status", None),
            started_at=getattr(r, "started_at", None),
            finished_at=getattr(r, "finished_at", None),
        )
        for r in rows
    ]

@router.get("/runs/last", response_model=RunSummary)
def get_last_run(db: Session = Depends(get_db)):
    q = db.query(RunORM)
    if _has_attr(RunORM, "started_at"):
        q = q.order_by(RunORM.started_at.desc())
    else:
        q = q.order_by(RunORM.id.desc())
    r = q.first()
    if not r:
        raise HTTPException(status_code=404, detail="no runs found")
    return RunSummary(
        id=r.id,
        title=getattr(r, "title", None),
        status=getattr(r, "status", None),
        started_at=getattr(r, "started_at", None),
        finished_at=getattr(r, "finished_at", None),
    )

@router.get("/runs/{run_id}/epics", response_model=List[EpicOut])
def get_epics_for_run(run_id: str, db: Session = Depends(get_db)):
    eps = (
        db.query(EpicORM)
        .filter(EpicORM.run_id == run_id)
        .order_by(EpicORM.priority_rank.asc())
        .all()
    )
    return [
        EpicOut(
            id=e.id,
            run_id=e.run_id,
            title=e.title,
            description=e.description or "",
            priority_rank=e.priority_rank or 1,
        )
        for e in eps
    ]

@router.get("/runs/{run_id}/stories", response_model=List[StoryOut])
def get_stories_for_run(
    run_id: str,
    epic_id: Optional[str] = Query(None, description="Filter by epic_id"),
    db: Session = Depends(get_db),
):
    q = db.query(StoryORM).filter(StoryORM.run_id == run_id)
    if epic_id:
        q = q.filter(StoryORM.epic_id == epic_id)
    rows = q.order_by(StoryORM.epic_id.asc(), StoryORM.priority_rank.asc()).all()
    return [
        StoryOut(
            id=s.id,
            run_id=s.run_id,
            epic_id=s.epic_id,
            title=s.title,
            description=s.description or "",
            priority_rank=s.priority_rank or 1,
        )
        for s in rows
    ]
