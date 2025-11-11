# app/core/runs.py
from __future__ import annotations
from typing import Dict
from sqlalchemy.orm import Session

from app.storage.models import (
    RequirementORM, ProductVisionORM, TechnicalSolutionORM,
    EpicORM, StoryORM, AcceptanceORM, TaskORM, DesignNoteORM, RunManifestORM, RunORM
)

def clear_plan_artifacts(db: Session, run_id: str) -> Dict[str, int]:
    """
    Delete plan artefacts for a run (epics, stories, tasks, acceptance, design notes),
    preserving ProductVision and TechnicalSolution.
    """
    counts: Dict[str, int] = {}
    # children → parents
    counts["acceptance"]   = db.query(AcceptanceORM).filter_by(run_id=run_id).delete(synchronize_session=False)
    counts["tasks"]        = db.query(TaskORM).filter_by(run_id=run_id).delete(synchronize_session=False)
    counts["stories"]      = db.query(StoryORM).filter_by(run_id=run_id).delete(synchronize_session=False)
    counts["epics"]        = db.query(EpicORM).filter_by(run_id=run_id).delete(synchronize_session=False)
    counts["design_notes"] = db.query(DesignNoteORM).filter_by(run_id=run_id).delete(synchronize_session=False)
    db.commit()
    return counts

def hard_delete_run(db: Session, run_id: str) -> Dict[str, int]:
    """
    Delete a run and all related artefacts (PV/TS included). Returns per-table delete counts.
    Raises ValueError if nothing exists for this run_id.
    """
    counts: Dict[str, int] = {}

    # children → parents
    counts["acceptance"]        = db.query(AcceptanceORM).filter_by(run_id=run_id).delete(synchronize_session=False)
    counts["tasks"]             = db.query(TaskORM).filter_by(run_id=run_id).delete(synchronize_session=False)
    counts["design_notes"]      = db.query(DesignNoteORM).filter_by(run_id=run_id).delete(synchronize_session=False)
    counts["stories"]           = db.query(StoryORM).filter_by(run_id=run_id).delete(synchronize_session=False)
    counts["epics"]             = db.query(EpicORM).filter_by(run_id=run_id).delete(synchronize_session=False)
    counts["product_vision"]    = db.query(ProductVisionORM).filter_by(run_id=run_id).delete(synchronize_session=False)
    counts["technical_solution"] = db.query(TechnicalSolutionORM).filter_by(run_id=run_id).delete(synchronize_session=False)
    counts["run_manifests"]     = db.query(RunManifestORM).filter_by(run_id=run_id).delete(synchronize_session=False)
    counts["runs"]              = db.query(RunORM).filter_by(id=run_id).delete(synchronize_session=False)

    deleted_total = sum(counts.values())
    if deleted_total == 0:
        db.rollback()
        raise ValueError(f"Run not found: {run_id}")

    db.commit()
    return counts