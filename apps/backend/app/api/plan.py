from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.models import PlanBundle
from app.storage.db import get_db
from app.core.planner import plan_run, read_plan

router = APIRouter()

@router.post("/runs/{run_id}/plan", response_model=PlanBundle)
def post_plan(run_id: str, db: Session = Depends(get_db)):
    try:
        return plan_run(db, run_id)
    except ValueError as e:
        # we use ValueError only for "requirement not found"
        if "requirement not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        # unexpected planner/LLM errors
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
