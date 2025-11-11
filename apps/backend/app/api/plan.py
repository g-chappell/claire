from __future__ import annotations
import os
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.configs.settings import get_settings
from app.core.rag_context import build_rag_context
from app.core.models import PlanBundle, ProductVision, TechnicalSolution
from app.storage.db import get_db
from app.core.planner import (
    plan_run,
    read_plan,
    generate_vision_solution,
    finalise_plan,
)
from app.storage.models import ProductVisionORM, TechnicalSolutionORM, RunManifestORM, RequirementORM

from app.core.runs import clear_plan_artifacts



logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/runs/{run_id}/plan", response_model=PlanBundle)
def post_plan(run_id: str, force: bool = False, db: Session = Depends(get_db)):
    """
    Idempotent plan generation: if a plan exists and force=False, return it.
    Otherwise, clear plan artefacts (PV/TS kept) and generate fresh.
    """
    try:
        if not force:
            try:
                return read_plan(db, run_id)
            except ValueError as e:
                if "plan not found" not in str(e).lower():
                    raise
        # plan missing OR force=True → start clean (keep PV/TS)
        clear_plan_artifacts(db, run_id)
        return plan_run(db, run_id)
    except ValueError as e:
        msg = str(e)
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except Exception:
        logger.exception("planning failed")
        raise HTTPException(status_code=500, detail="planning failed")

@router.get("/runs/{run_id}/plan", response_model=PlanBundle)
def get_plan(run_id: str, db: Session = Depends(get_db)):
    try:
        return read_plan(db, run_id)
    except ValueError as e:
        if "plan not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="failed to load plan")

# ---------- NEW: Stage-gate models ----------

class VisionSolutionOut(BaseModel):
    product_vision: ProductVision
    technical_solution: TechnicalSolution

class VisionSolutionUpdate(BaseModel):
    product_vision: Optional[ProductVision] = None
    technical_solution: Optional[TechnicalSolution] = None


# ---------- Helper to mark gate status on manifest (optional but useful) ----------

def _set_gate_status(db: Session, run_id: str, status: str) -> None:
    mf = db.query(RunManifestORM).filter_by(run_id=run_id).first()
    if not mf:
        return
    data = dict(mf.data or {})
    data["vision_solution_status"] = status  # "draft" or "approved"
    mf.data = data
    db.add(mf)
    db.commit()


# ---------- NEW: Stage 1 — generate/read/update PV/TS ----------

@router.post("/runs/{run_id}/plan/vision-solution", response_model=VisionSolutionOut)
def post_vision_solution(run_id: str,request: Request, use_rag: bool | None = Query(default=None), db: Session = Depends(get_db), settings = Depends(get_settings),):
    """
    Generate *only* the Product Vision & Technical Solution for this run,
    persist them, and return them. Does not create epics/stories yet.
    """
    try:
        # --- Optional RAG context (feature-flagged) ---
        rag_context = ""
        enabled = use_rag if use_rag is not None else settings.USE_RAG
        store_cls = type(request.app.state.memory).__name__
        logger.info("RAG: enabled=%s (env=%s param=%s) store=%s",
                    enabled, settings.USE_RAG, use_rag, store_cls)
        if enabled:
            # Grab the run's requirement to form the retrieval query
            req = db.query(RequirementORM).filter_by(run_id=run_id).first()
            if req:
                ctx_text, _hits = build_rag_context(
                    request,
                    requirement_title=req.title,
                    requirement_description=req.description,
                    types=("product_vision", "technical_solution"),
                    top_k=settings.RAG_TOP_K,
                )
                logger.info("RAG: build_rag_context -> %d hits, ctx_len=%d",
                len(_hits), len(ctx_text))
                rag_context = ctx_text
        pv, ts = generate_vision_solution(db, run_id, rag_context=rag_context)
        # Mark gate as "draft" until user approves/finalises
        _set_gate_status(db, run_id, "draft")
        return {"product_vision": pv, "technical_solution": ts}
    except ValueError as e:
        msg = str(e)
        if "requirement not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except Exception as e:
        logger.exception("vision-solution generation failed")
        raise HTTPException(status_code=500, detail="failed to generate vision/solution")


@router.get("/runs/{run_id}/plan/vision-solution", response_model=VisionSolutionOut)
def get_vision_solution(run_id: str, db: Session = Depends(get_db)):
    """
    Read the currently stored Product Vision & Technical Solution.
    """
    pv = db.query(ProductVisionORM).filter_by(run_id=run_id).first()
    ts = db.query(TechnicalSolutionORM).filter_by(run_id=run_id).first()
    if not pv or not ts:
        raise HTTPException(status_code=404, detail="vision/solution not found for run")
    return {"product_vision": pv.data, "technical_solution": ts.data}


@router.put("/runs/{run_id}/plan/vision-solution", response_model=VisionSolutionOut)
def put_vision_solution(run_id: str, payload: VisionSolutionUpdate, db: Session = Depends(get_db)):
    """
    Update (upsert) Product Vision and/or Technical Solution before finalising.
    """
    pv_row = db.query(ProductVisionORM).filter_by(run_id=run_id).first()
    ts_row = db.query(TechnicalSolutionORM).filter_by(run_id=run_id).first()
    if not pv_row and not payload.product_vision:
        raise HTTPException(status_code=404, detail="product_vision not found; provide product_vision to create")
    if not ts_row and not payload.technical_solution:
        raise HTTPException(status_code=404, detail="technical_solution not found; provide technical_solution to create")

    if payload.product_vision is not None:
        if pv_row is None:
            pv_row = ProductVisionORM(run_id=run_id, data=payload.product_vision.model_dump())
        else:
            pv_row.data = payload.product_vision.model_dump()
        db.add(pv_row)

    if payload.technical_solution is not None:
        if ts_row is None:
            ts_row = TechnicalSolutionORM(run_id=run_id, data=payload.technical_solution.model_dump())
        else:
            ts_row.data = payload.technical_solution.model_dump()
        db.add(ts_row)

    db.commit()
    _set_gate_status(db, run_id, "draft")

    # Return whatever is now stored (prefer fresh objects to avoid partials)
    pv = db.query(ProductVisionORM).filter_by(run_id=run_id).first()
    ts = db.query(TechnicalSolutionORM).filter_by(run_id=run_id).first()
    assert pv and ts  # both must exist after the upsert logic above
    return {"product_vision": pv.data, "technical_solution": ts.data}


# ---------- NEW: Stage 2 — finalise (generate the rest of the plan) ----------

@router.post("/runs/{run_id}/plan/finalise", response_model=PlanBundle)
def post_finalise(
    run_id: str,
    body: Optional[VisionSolutionUpdate] = None,
    db: Session = Depends(get_db),
):
    """
    Clear previous plan artefacts for this run (PV/TS remain), then generate epics/stories/tasks (and notes/QA if enabled).
    """
    try:
        clear_plan_artifacts(db, run_id)

        vo = body.product_vision.model_dump() if (body and body.product_vision) else None
        so = body.technical_solution.model_dump() if (body and body.technical_solution) else None

        bundle = finalise_plan(db, run_id, vision_override=vo, solution_override=so)
        _set_gate_status(db, run_id, "approved")
        return bundle
    except ValueError as e:
        msg = str(e)
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except Exception:
        logger.exception("finalise failed")
        raise HTTPException(status_code=500, detail="finalise failed")
