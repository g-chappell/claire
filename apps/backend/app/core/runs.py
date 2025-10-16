# app/core/runs.py
from __future__ import annotations
from sqlalchemy.orm import Session

from app.storage.models import (
    RequirementORM, ProductVisionORM, TechnicalSolutionORM,
    EpicORM, StoryORM, AcceptanceORM, TaskORM, DesignNoteORM, RunManifestORM, RunORM
)

def hard_delete_run(db: Session, run_id: str) -> dict:
    """Delete all artifacts for a run. Always returns counts; does not raise if already deleted."""
    counts: dict[str, int] = {}

    # children → parents
    counts["acceptance"]          = db.query(AcceptanceORM).filter_by(run_id=run_id).delete(synchronize_session=False)
    counts["tasks"]               = db.query(TaskORM).filter_by(run_id=run_id).delete(synchronize_session=False)
    counts["stories"]             = db.query(StoryORM).filter_by(run_id=run_id).delete(synchronize_session=False)
    counts["epics"]               = db.query(EpicORM).filter_by(run_id=run_id).delete(synchronize_session=False)
    counts["design_notes"]        = db.query(DesignNoteORM).filter_by(run_id=run_id).delete(synchronize_session=False)
    counts["product_vision"]      = db.query(ProductVisionORM).filter_by(run_id=run_id).delete(synchronize_session=False)
    counts["technical_solution"]  = db.query(TechnicalSolutionORM).filter_by(run_id=run_id).delete(synchronize_session=False)
    counts["requirements"]        = db.query(RequirementORM).filter_by(run_id=run_id).delete(synchronize_session=False)

    # finally manifest + run
    counts["manifest"]            = db.query(RunManifestORM).filter_by(run_id=run_id).delete(synchronize_session=False)
    counts["runs"]                = db.query(RunORM).filter_by(id=run_id).delete(synchronize_session=False)

    db.commit()
    return counts