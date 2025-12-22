from __future__ import annotations
import os
import logging
from typing import Optional, Callable, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.configs.settings import get_settings
from app.core.rag_context import build_exemplar_context
from app.core.models import PlanBundle, ProductVision, TechnicalSolution, Story
from app.storage.db import get_db
from app.core.planner import (
    read_plan,
    generate_vision_solution,
    finalise_plan,
)
from app.storage.models import ProductVisionORM, TechnicalSolutionORM, EpicORM, StoryORM, TaskORM, RunManifestORM, RequirementORM

from app.core.runs import clear_plan_artifacts



logger = logging.getLogger(__name__)

router = APIRouter()

class FeedbackPatch(BaseModel):
    feedback_human: Optional[str] = None
    feedback_ai: Optional[str] = None

@router.post("/runs/{run_id}/plan", response_model=PlanBundle)
def post_plan(
    run_id: str,
    request: Request,
    force: bool = False,
    use_rag: bool | None = Query(default=None),
    db: Session = Depends(get_db),
    settings = Depends(get_settings),
):
    """
    Idempotent plan generation: if a plan exists and force=False, return it.
    Otherwise, clear plan artefacts (PV/TS kept) and generate fresh.

    Option A: ensure this endpoint also uses exemplar-only RAG retrieval (top-1 per artefact type),
    consistent with the stage-gate endpoints.
    """
    try:
        if not force:
            try:
                return read_plan(db, run_id)
            except ValueError as e:
                if "plan not found" not in str(e).lower():
                    raise

        # plan missing OR force=True → start clean (keep PV/TS rows, but we will regenerate them below)
        clear_plan_artifacts(db, run_id)

        # ---- Determine whether RAG is enabled (query param > manifest > env) ----
        mf = db.query(RunManifestORM).filter_by(run_id=run_id).first()
        mf_data = dict(mf.data or {}) if mf and getattr(mf, "data", None) else {}
        manifest_use_rag = mf_data.get("use_rag")
        exp_label = mf_data.get("experiment_label")
        prompt_mode = mf_data.get(
            "prompt_context_mode",
            getattr(settings, "PROMPT_CONTEXT_MODE", "structured"),
        )

        # ---- Determine whether RAG is enabled (query param > manifest; NO env fallback) ----
        if use_rag is not None:
            enabled = bool(use_rag)
            source = "query_param"
        elif manifest_use_rag is not None:
            enabled = bool(manifest_use_rag)
            source = "manifest"
        else:
            enabled = False
            source = "default_false"

        store_cls = type(request.app.state.memory).__name__
        logger.info(
            "RAG_PLAN run=%s exp=%s enabled=%s source=%s manifest_use_rag=%s param_use_rag=%s store=%s",
            run_id,
            exp_label,
            enabled,
            source,
            manifest_use_rag,
            use_rag,
            store_cls,
        )

        # ---- Exemplar-only retrieval (top-1 per artefact type) ----
        pv_exemplar = ""
        ts_exemplar = ""
        ra_exemplar = ""
        qa_exemplar = ""
        dn_exemplar = ""
        st_exemplar = ""

        # Always define these so they exist when we call finalise_plan()
        req: Optional[RequirementORM] = None
        tasks_exemplar_resolver: Optional[Callable[[Story], str]] = None

        if enabled:
            req = db.query(RequirementORM).filter_by(run_id=run_id).first()
            if req:
                pv_exemplar, pv_hits = build_exemplar_context(
                    request,
                    query_title=req.title or "",
                    query_description=req.description or "",
                    artifact_type="product_vision",
                    top_k=1,
                    run_id=run_id,
                    experiment_label=exp_label,
                    prompt_context_mode=prompt_mode,
                    phase="planning",
                )
                ts_exemplar, ts_hits = build_exemplar_context(
                    request,
                    query_title=req.title or "",
                    query_description=req.description or "",
                    artifact_type="technical_solution",
                    top_k=1,
                    run_id=run_id,
                    experiment_label=exp_label,
                    prompt_context_mode=prompt_mode,
                    phase="planning",
                )
                ra_exemplar, ra_hits = build_exemplar_context(
                    request,
                    query_title=req.title or "",
                    query_description=req.description or "",
                    artifact_type="ra_plan",
                    top_k=1,
                    run_id=run_id,
                    experiment_label=exp_label,
                    prompt_context_mode=prompt_mode,
                    phase="planning",
                )

                if getattr(settings, "FEATURE_QA", False):
                    qa_exemplar, qa_hits = build_exemplar_context(
                        request,
                        query_title=req.title or "",
                        query_description=req.description or "",
                        artifact_type="qa_spec",
                        top_k=1,
                        run_id=run_id,
                        experiment_label=exp_label,
                        prompt_context_mode=prompt_mode,
                        phase="planning",
                    )
                else:
                    qa_hits = []

                if getattr(settings, "FEATURE_DESIGN_NOTES", False):
                    dn_exemplar, dn_hits = build_exemplar_context(
                        request,
                        query_title=req.title or "",
                        query_description=req.description or "",
                        artifact_type="design_notes",
                        top_k=1,
                        run_id=run_id,
                        experiment_label=exp_label,
                        prompt_context_mode=prompt_mode,
                        phase="planning",
                    )
                else:
                    dn_hits = []

                # NOTE(Stage 1): story_tasks exemplars must be STORY-based only.
                # Do NOT retrieve a run-level story_tasks exemplar using requirement title/desc.
                st_exemplar, st_hits = "", []

                # ---- Per-story tasks exemplar resolver (TOP-1 per story), fallback disabled (empty) ----
                tasks_exemplar_cache: Dict[str, str] = {}
                fallback_story_tasks = ""

                def _tasks_exemplar_for_story(story: Story) -> str:
                    key = ((getattr(story, "id", None) or story.title or "").strip().lower())
                    if key in tasks_exemplar_cache:
                        return tasks_exemplar_cache[key]

                    # Query should be STORY-based so we retrieve similar stories,
                    # while the stored exemplar text can include tasks + feedback.
                    q_title = (story.title or "").strip()
                    q_desc = (story.description or "").strip()

                    ex, hits = build_exemplar_context(
                        request,
                        query_title=q_title,
                        query_description=q_desc,
                        artifact_type="story_tasks",
                        top_k=1,
                        run_id=run_id,
                        experiment_label=exp_label,
                        prompt_context_mode=prompt_mode,
                        phase="planning",
                    )

                    sim = None
                    hit_id = "n/a"
                    if hits:
                        hit_id = getattr(hits[0], "id", "") or "n/a"
                        try:
                            sim = float((hits[0].meta or {}).get("debug_similarity"))  # type: ignore[arg-type]
                        except Exception:
                            sim = None

                    found = bool((ex or "").strip())
                    logger.info(
                        "RAG_STORY_TASKS_MATCH run=%s story_id=%s story_title=%s found=%s sim=%s hit_id=%s",
                        run_id,
                        getattr(story, "id", "") or "",
                        (story.title or "")[:120],
                        found,
                        f"{sim:.4f}" if sim is not None else "n/a",
                        hit_id,
                    )

                    picked = (ex or "").strip() or fallback_story_tasks
                    tasks_exemplar_cache[key] = picked
                    return picked
                
                tasks_exemplar_resolver = _tasks_exemplar_for_story

                logger.info(
                    "RAG_EXEMPLARS_PLAN run=%s exp=%s pv_hits=%d pv_len=%d ts_hits=%d ts_len=%d ra_hits=%d ra_len=%d qa_hits=%d qa_len=%d dn_hits=%d dn_len=%d st_hits=%d st_len=%d",
                    run_id,
                    exp_label,
                    len(pv_hits or []),
                    len(pv_exemplar or ""),
                    len(ts_hits or []),
                    len(ts_exemplar or ""),
                    len(ra_hits or []),
                    len(ra_exemplar or ""),
                    len(qa_hits or []),
                    len(qa_exemplar or ""),
                    len(dn_hits or []),
                    len(dn_exemplar or ""),
                    len(st_hits or []),
                    len(st_exemplar or ""),
                )
        else:
            logger.info("RAG_PLAN run=%s exp=%s disabled; skipping exemplar retrieval", run_id, exp_label)

        # ---- Stage 1 (PV/TS) using PV/TS exemplars ----
        pv, ts = generate_vision_solution(
            db,
            run_id,
            exemplars={
                "product_vision": (pv_exemplar or "").strip(),
                "technical_solution": (ts_exemplar or "").strip(),
            },
        )
        _set_gate_status(db, run_id, "draft")

        # ---- Stage 2 (rest of plan) using RA/QA/DN/StoryTasks exemplars ----
        bundle = finalise_plan(
            db,
            run_id,
            exemplars={
                "ra_plan": (ra_exemplar or "").strip(),
                "qa_spec": (qa_exemplar or "").strip(),
                "design_notes": (dn_exemplar or "").strip(),
                "story_tasks": (st_exemplar or "").strip(),
            },
            tasks_exemplar_resolver=tasks_exemplar_resolver,
        )
        _set_gate_status(db, run_id, "approved")
        return bundle

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
def post_vision_solution(
    run_id: str,
    request: Request,
    use_rag: bool | None = Query(default=None),
    db: Session = Depends(get_db),
    settings = Depends(get_settings),
):
    """
    Generate *only* the Product Vision & Technical Solution for this run,
    persist them, and return them. Does not create epics/stories yet.
    """
    try:
        # ---- Determine whether RAG is enabled (query param > manifest > env) ----
        mf = db.query(RunManifestORM).filter_by(run_id=run_id).first()
        mf_data = dict(mf.data or {}) if mf and getattr(mf, "data", None) else {}
        manifest_use_rag = mf_data.get("use_rag")
        exp_label = mf_data.get("experiment_label")
        prompt_mode = mf_data.get(
            "prompt_context_mode",
            getattr(settings, "PROMPT_CONTEXT_MODE", "structured"),
        )

        if use_rag is not None:
            enabled = use_rag
            source = "query_param"
        elif manifest_use_rag is not None:
            enabled = bool(manifest_use_rag)
            source = "manifest"
        else:
            enabled = settings.USE_RAG
            source = "env"

        store_cls = type(request.app.state.memory).__name__
        logger.info(
            "RAG_GATE run=%s exp=%s enabled=%s source=%s manifest_use_rag=%s param_use_rag=%s store=%s",
            run_id,
            exp_label,
            enabled,
            source,
            manifest_use_rag,
            use_rag,
            store_cls,
        )

        # ---- Exemplar-only retrieval (top-1 per artefact type) ----
        exemplars: dict[str, str] = {
            "product_vision": "",
            "technical_solution": "",
        }

        if enabled:
            req = db.query(RequirementORM).filter_by(run_id=run_id).first()
            if req:
                pv_ex, pv_hits = build_exemplar_context(
                    request,
                    query_title=req.title or "",
                    query_description=req.description or "",
                    artifact_type="product_vision",
                    top_k=1,  # hard top-1
                    run_id=run_id,
                    experiment_label=exp_label,
                    prompt_context_mode=prompt_mode,
                    phase="planning",
                )
                ts_ex, ts_hits = build_exemplar_context(
                    request,
                    query_title=req.title or "",
                    query_description=req.description or "",
                    artifact_type="technical_solution",
                    top_k=1,  # hard top-1
                    run_id=run_id,
                    experiment_label=exp_label,
                    prompt_context_mode=prompt_mode,
                    phase="planning",
                )

                exemplars["product_vision"] = pv_ex or ""
                exemplars["technical_solution"] = ts_ex or ""

                logger.info(
                    "RAG_EXEMPLARS run=%s exp=%s pv_hits=%d pv_len=%d ts_hits=%d ts_len=%d",
                    run_id,
                    exp_label,
                    len(pv_hits or []),
                    len(exemplars["product_vision"]),
                    len(ts_hits or []),
                    len(exemplars["technical_solution"]),
                )
        else:
            logger.info("RAG_GATE run=%s exp=%s disabled; skipping exemplar retrieval", run_id, exp_label)

        # ---- Generate PV/TS, passing exemplars down (NOT appended into requirement text) ----
        pv, ts = generate_vision_solution(db, run_id, exemplars=exemplars)

        # Mark gate as draft until approved/finalised
        _set_gate_status(db, run_id, "draft")
        return {"product_vision": pv, "technical_solution": ts}

    except ValueError as e:
        msg = str(e)
        if "requirement not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except Exception:
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
    request: Request,
    body: Optional[VisionSolutionUpdate] = None,
    use_rag: bool | None = Query(default=None),
    db: Session = Depends(get_db),
    settings = Depends(get_settings),
):
    """
    Clear previous plan artefacts for this run (PV/TS remain), then generate epics/stories/tasks
    (and notes/QA if enabled).
    """
    try:
        clear_plan_artifacts(db, run_id)

        vo = body.product_vision.model_dump() if (body and body.product_vision) else None
        so = body.technical_solution.model_dump() if (body and body.technical_solution) else None

        # ---- Determine whether RAG is enabled (query param > manifest > env) ----
        mf = db.query(RunManifestORM).filter_by(run_id=run_id).first()
        mf_data = dict(mf.data or {}) if mf and getattr(mf, "data", None) else {}
        manifest_use_rag = mf_data.get("use_rag")
        exp_label = mf_data.get("experiment_label")
        prompt_mode = mf_data.get(
            "prompt_context_mode",
            getattr(settings, "PROMPT_CONTEXT_MODE", "structured"),
        )

        if use_rag is not None:
            enabled = use_rag
            source = "query_param"
        elif manifest_use_rag is not None:
            enabled = bool(manifest_use_rag)
            source = "manifest"
        else:
            enabled = settings.USE_RAG
            source = "env"

        store_cls = type(request.app.state.memory).__name__
        logger.info(
            "RAG_GATE_FINALISE run=%s exp=%s enabled=%s source=%s manifest_use_rag=%s param_use_rag=%s store=%s",
            run_id,
            exp_label,
            enabled,
            source,
            manifest_use_rag,
            use_rag,
            store_cls,
        )

        # ---- Exemplar-only retrieval (top-1 per artefact type) ----
        exemplars: dict[str, str] = {
            "ra_plan": "",
            "qa_spec": "",
            "design_notes": "",
            "story_tasks": "",
        }

        req = None
        if enabled:
            req = db.query(RequirementORM).filter_by(run_id=run_id).first()
            if req:
                # RA plan exemplar (epics+stories)
                ra_ex, ra_hits = build_exemplar_context(
                    request,
                    query_title=req.title or "",
                    query_description=req.description or "",
                    artifact_type="ra_plan",
                    top_k=1,
                    run_id=run_id,
                    experiment_label=exp_label,
                    prompt_context_mode=prompt_mode,
                    phase="planning",
                )
                exemplars["ra_plan"] = ra_ex or ""

                # QA exemplar (only if feature enabled)
                if getattr(settings, "FEATURE_QA", False):
                    qa_ex, qa_hits = build_exemplar_context(
                        request,
                        query_title=req.title or "",
                        query_description=req.description or "",
                        artifact_type="qa_spec",
                        top_k=1,
                        run_id=run_id,
                        experiment_label=exp_label,
                        prompt_context_mode=prompt_mode,
                        phase="planning",
                    )
                    exemplars["qa_spec"] = qa_ex or ""
                else:
                    qa_hits = []

                # Design notes exemplar (only if feature enabled)
                if getattr(settings, "FEATURE_DESIGN_NOTES", False):
                    dn_ex, dn_hits = build_exemplar_context(
                        request,
                        query_title=req.title or "",
                        query_description=req.description or "",
                        artifact_type="design_notes",
                        top_k=1,
                        run_id=run_id,
                        experiment_label=exp_label,
                        prompt_context_mode=prompt_mode,
                        phase="planning",
                    )
                    exemplars["design_notes"] = dn_ex or ""
                else:
                    dn_hits = []

                # NOTE(Stage 1): story_tasks exemplars must be STORY-based only.
                # Do NOT retrieve story_tasks using requirement title/desc.
                st_hits = []
                exemplars["story_tasks"] = ""

                logger.info(
                    "RAG_EXEMPLARS_FINALISE run=%s exp=%s ra_hits=%d ra_len=%d qa_hits=%d qa_len=%d dn_hits=%d dn_len=%d st_hits=%d st_len=%d",
                    run_id,
                    exp_label,
                    len(ra_hits or []),
                    len(exemplars["ra_plan"]),
                    len(qa_hits or []),
                    len(exemplars["qa_spec"]),
                    len(dn_hits or []),
                    len(exemplars["design_notes"]),
                    len(st_hits or []),
                    len(exemplars["story_tasks"]),
                )
        else:
            logger.info("RAG_GATE_FINALISE run=%s exp=%s disabled; skipping exemplar retrieval", run_id, exp_label)

        # ---- Per-story tasks exemplar resolver (TOP-1 per story), fallback to run-level story_tasks exemplar ----
        req_title = (req.title or "").strip() if req else ""
        req_description = (req.description or "").strip() if req else ""
        tasks_exemplar_cache: Dict[str, str] = {}
        fallback_story_tasks = (exemplars.get("story_tasks") or "").strip()

        tasks_exemplar_resolver: Optional[Callable[[Story], str]] = None

        def _tasks_exemplar_for_story(story: Story) -> str:
            key = ((getattr(story, "id", None) or story.title or "").strip().lower())
            if key in tasks_exemplar_cache:
                return tasks_exemplar_cache[key]

            # Query should be STORY-based so we retrieve similar stories,
            # while the stored exemplar text can include tasks + feedback.
            q_title = (story.title or "").strip()
            q_desc = (story.description or "").strip()

            ex, hits = build_exemplar_context(
                request,
                query_title=q_title,
                query_description=q_desc,
                artifact_type="story_tasks",
                top_k=1,
                run_id=run_id,
                experiment_label=exp_label,
                prompt_context_mode=prompt_mode,
                phase="planning",
            )

            sim = None
            hit_id = "n/a"
            if hits:
                hit_id = getattr(hits[0], "id", "") or "n/a"
                try:
                    sim = float((hits[0].meta or {}).get("debug_similarity"))  # type: ignore[arg-type]
                except Exception:
                    sim = None

            found = bool((ex or "").strip())
            logger.info(
                "RAG_STORY_TASKS_MATCH run=%s story_id=%s story_title=%s found=%s sim=%s hit_id=%s",
                run_id,
                getattr(story, "id", "") or "",
                (story.title or "")[:120],
                found,
                f"{sim:.4f}" if sim is not None else "n/a",
                hit_id,
            )

            picked = (ex or "").strip() or fallback_story_tasks
            tasks_exemplar_cache[key] = picked
            return picked

        if enabled and req:
            tasks_exemplar_resolver = _tasks_exemplar_for_story

        bundle = finalise_plan(
            db,
            run_id,
            vision_override=vo,
            solution_override=so,
            exemplars=exemplars,
            tasks_exemplar_resolver=tasks_exemplar_resolver,
        )
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
    
# ---- Product Vision feedback (persists inside pv.data) ----
@router.put("/runs/{run_id}/plan/vision/feedback")
def put_pv_feedback(run_id: str, payload: FeedbackPatch, db: Session = Depends(get_db)):
    pv = db.query(ProductVisionORM).filter_by(run_id=run_id).first()
    if not pv:
        raise HTTPException(status_code=404, detail="product_vision not found")
    data = dict(pv.data or {})
    if payload.feedback_human is not None:
        data["feedback_human"] = payload.feedback_human
    if payload.feedback_ai is not None:
        data["feedback_ai"] = payload.feedback_ai
    pv.data = data
    db.add(pv); db.commit()
    return pv.data

# ---- Technical Solution feedback (persists inside ts.data) ----
@router.put("/runs/{run_id}/plan/solution/feedback")
def put_ts_feedback(run_id: str, payload: FeedbackPatch, db: Session = Depends(get_db)):
    ts = db.query(TechnicalSolutionORM).filter_by(run_id=run_id).first()
    if not ts:
        raise HTTPException(status_code=404, detail="technical_solution not found")
    data = dict(ts.data or {})
    if payload.feedback_human is not None:
        data["feedback_human"] = payload.feedback_human
    if payload.feedback_ai is not None:
        data["feedback_ai"] = payload.feedback_ai
    ts.data = data
    db.add(ts); db.commit()
    return ts.data

# ---- Epic / Story / Task feedback (columnar overwrite) ----
@router.put("/runs/{run_id}/plan/epics/{epic_id}/feedback")
def put_epic_feedback(run_id: str, epic_id: str, payload: FeedbackPatch, db: Session = Depends(get_db)):
    row = db.query(EpicORM).filter_by(run_id=run_id, id=epic_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="epic not found")
    if payload.feedback_human is not None:
        row.feedback_human = payload.feedback_human
    if payload.feedback_ai is not None:
        row.feedback_ai = payload.feedback_ai
    db.add(row); db.commit()
    return {"id": row.id, "feedback_human": row.feedback_human, "feedback_ai": row.feedback_ai}

@router.put("/runs/{run_id}/plan/stories/{story_id}/feedback")
def put_story_feedback(run_id: str, story_id: str, payload: FeedbackPatch, db: Session = Depends(get_db)):
    row = db.query(StoryORM).filter_by(run_id=run_id, id=story_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="story not found")
    if payload.feedback_human is not None:
        row.feedback_human = payload.feedback_human
    if payload.feedback_ai is not None:
        row.feedback_ai = payload.feedback_ai
    db.add(row); db.commit()
    return {"id": row.id, "feedback_human": row.feedback_human, "feedback_ai": row.feedback_ai}

@router.put("/runs/{run_id}/plan/tasks/{task_id}/feedback")
def put_task_feedback(run_id: str, task_id: str, payload: FeedbackPatch, db: Session = Depends(get_db)):
    row = db.query(TaskORM).filter_by(run_id=run_id, id=task_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="task not found")
    if payload.feedback_human is not None:
        row.feedback_human = payload.feedback_human
    if payload.feedback_ai is not None:
        row.feedback_ai = payload.feedback_ai
    db.add(row); db.commit()
    return {"id": row.id, "feedback_human": row.feedback_human, "feedback_ai": row.feedback_ai}
