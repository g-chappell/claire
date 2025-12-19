# app/api/runs_qol.py
from __future__ import annotations
from datetime import datetime
from typing import Optional, List, Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
import uuid, json

from app.storage.db import get_db
from app.storage.models import (
    RunORM,
    EpicORM,
    StoryORM,
    TaskORM,
    ProductVisionORM,
    TechnicalSolutionORM,
    RequirementORM,
    RunManifestORM,
    PlanArtifactFeedbackORM
)
from app.core.planner import read_plan
from app.configs.settings import get_settings
from app.core.memory import MemoryDoc

from app.agents.meta.scrum_master_lc import generate_ai_feedback, generate_ai_feedback_from_context

router = APIRouter()

# ---- Schemas (lightweight, API-only) ----
from pydantic import BaseModel

PlanKind = Literal["product_vision", "technical_solution", "ra_plan", "story_tasks"]

class PlanFeedbackIn(BaseModel):
    human: Optional[str] = None
    ai: Optional[str] = None
    story_id: Optional[str] = None  # required when kind == "story_tasks"

class PlanAIFeedbackIn(BaseModel):
    human_override: Optional[str] = None
    story_id: Optional[str] = None  # required when kind == "story_tasks"

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

def _get_or_create_plan_feedback(
    db: Session, *, run_id: str, kind: PlanKind, story_id: Optional[str]
) -> PlanArtifactFeedbackORM:
    row = (
        db.query(PlanArtifactFeedbackORM)
        .filter_by(run_id=run_id, kind=kind, story_id=story_id)
        .first()
    )
    if row:
        return row
    row = PlanArtifactFeedbackORM(
        id=f"{run_id}:{kind}:{story_id or 'run'}:{uuid.uuid4().hex[:6]}",
        run_id=run_id,
        kind=kind,
        story_id=story_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row

def _build_plan_context(db: Session, *, run_id: str, kind: PlanKind, story_id: Optional[str]) -> str:
    if kind == "product_vision":
        pv = db.query(ProductVisionORM).filter_by(run_id=run_id).first()
        return "PRODUCT VISION\n" + (json.dumps(pv.data, indent=2, ensure_ascii=False) if pv and pv.data else "(none)")

    if kind == "technical_solution":
        ts = db.query(TechnicalSolutionORM).filter_by(run_id=run_id).first()
        return "TECHNICAL SOLUTION\n" + (json.dumps(ts.data, indent=2, ensure_ascii=False) if ts and ts.data else "(none)")

    if kind == "ra_plan":
        epics = db.query(EpicORM).filter(EpicORM.run_id == run_id).order_by(EpicORM.priority_rank.asc()).all()
        stories = db.query(StoryORM).filter(StoryORM.run_id == run_id).order_by(StoryORM.epic_id.asc(), StoryORM.priority_rank.asc()).all()
        bundle = []
        by_epic: dict[str, list[StoryORM]] = {}
        for s in stories:
            by_epic.setdefault(s.epic_id, []).append(s)
        for e in epics:
            bundle.append({
                "epic": {"id": str(e.id), "title": e.title, "description": e.description or "", "priority_rank": int(e.priority_rank or 1)},
                "stories": [{"id": str(s.id), "title": s.title, "description": s.description or "", "priority_rank": int(s.priority_rank or 1)} for s in by_epic.get(e.id, [])],
            })
        return "RA PLAN (EPICS & STORIES)\n" + json.dumps({"epics_and_stories": bundle}, indent=2, ensure_ascii=False)

    # story_tasks (per story)
    if not story_id:
        return "(missing story_id for story_tasks)"
    s = db.get(StoryORM, story_id)
    if not s or s.run_id != run_id:
        return "(story not found)"
    tasks = (
        db.query(TaskORM)
        .filter(TaskORM.run_id == run_id, TaskORM.story_id == story_id)
        .order_by(TaskORM.order.asc())
        .all()
    )
    obj = {
        "story": {"id": str(s.id), "title": s.title, "description": s.description or ""},
        "tasks": [{"id": str(t.id), "title": t.title, "definition_of_done": t.definition_of_done, "order": t.order} for t in tasks],
    }
    return "STORY TASKS\n" + json.dumps(obj, indent=2, ensure_ascii=False)



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

class FeedbackIn(BaseModel):
    human: Optional[str] = None
    ai: Optional[str] = None

def _load_artefact(db: Session, kind: Literal["epic","story","task"], artefact_id: str):
    if kind == "epic":
        return db.get(EpicORM, artefact_id)
    if kind == "story":
        return db.get(StoryORM, artefact_id)
    return db.get(TaskORM, artefact_id)




@router.patch("/runs/{run_id}/plan/{kind}/feedback")
def patch_plan_feedback_v2(
    run_id: str,
    kind: PlanKind,
    body: PlanFeedbackIn,
    db: Session = Depends(get_db),
):
    story_id = body.story_id if kind == "story_tasks" else None
    if kind == "story_tasks" and not story_id:
        raise HTTPException(status_code=400, detail="story_id is required for kind=story_tasks")

    row = _get_or_create_plan_feedback(db, run_id=run_id, kind=kind, story_id=story_id)

    if body.human is not None:
        row.feedback_human = body.human.strip()
    if body.ai is not None:
        row.feedback_ai = body.ai.strip()

    db.add(row); db.commit(); db.refresh(row)
    return {"ok": True, "kind": kind, "story_id": story_id, "human": row.feedback_human, "ai": row.feedback_ai}


@router.post("/runs/{run_id}/plan/{kind}/feedback/ai")
def synthesize_plan_ai_feedback_v2(
    run_id: str,
    kind: PlanKind,
    body: PlanAIFeedbackIn,
    db: Session = Depends(get_db),
):
    story_id = body.story_id if kind == "story_tasks" else None
    if kind == "story_tasks" and not story_id:
        raise HTTPException(status_code=400, detail="story_id is required for kind=story_tasks")

    row = _get_or_create_plan_feedback(db, run_id=run_id, kind=kind, story_id=story_id)

    context_block = _build_plan_context(db, run_id=run_id, kind=kind, story_id=story_id)

    ai_text, model_used = generate_ai_feedback_from_context(
        db,
        run_id=run_id,
        kind=kind,
        context_block=context_block,
        human_feedback=(body.human_override or row.feedback_human),
        story_id=story_id,
        metadata={"kind": kind, "story_id": story_id} if story_id else {"kind": kind},
    )

    row.feedback_ai = ai_text
    db.add(row); db.commit(); db.refresh(row)
    return {"ok": True, "kind": kind, "story_id": story_id, "ai": row.feedback_ai, "model": model_used}



@router.patch("/runs/{run_id}/{kind}/{artefact_id}/feedback")
def patch_feedback(
    run_id: str,
    kind: Literal["epic","story","task"],
    artefact_id: str,
    body: FeedbackIn,
    db: Session = Depends(get_db),
):
    obj = _load_artefact(db, kind, artefact_id)
    if not obj or obj.run_id != run_id:
        raise HTTPException(status_code=404, detail="Artefact not found")

    changed = False
    if body.human is not None:
        obj.feedback_human = body.human.strip()
        changed = True
    if body.ai is not None:
        obj.feedback_ai = body.ai.strip()
        changed = True

    if changed:
        db.add(obj)
        db.commit()
        db.refresh(obj)
    return {"ok": True, "id": artefact_id, "kind": kind, "human": obj.feedback_human, "ai": obj.feedback_ai}

class AIFeedbackIn(BaseModel):
    # Optional: allow passing human override; else use stored human feedback
    human_override: Optional[str] = None

@router.post("/runs/{run_id}/{kind}/{artefact_id}/feedback/ai")
def synthesize_ai_feedback(
    run_id: str,
    kind: Literal["epic","story","task"],
    artefact_id: str,
    body: AIFeedbackIn,
    db: Session = Depends(get_db),
):
    obj = _load_artefact(db, kind, artefact_id)
    if not obj or obj.run_id != run_id:
        raise HTTPException(status_code=404, detail="Artefact not found")

    # Generate AI feedback
    ai_text, model_used = generate_ai_feedback(
        db, run_id=run_id, kind=kind, artefact_id=artefact_id,
        human_feedback=body.human_override or obj.feedback_human
    )
    obj.feedback_ai = ai_text
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return {"ok": True, "ai": obj.feedback_ai, "model": model_used}

@router.post("/runs/{run_id}/retrospective/commit-exemplars")
def commit_exemplars(
    run_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings = Depends(get_settings),
):
    """
    Commit "good examples" into the RAG store at the SAME levels the planner retrieves:
    - product_vision
    - technical_solution
    - ra_plan (epics+stories as a bundle)
    - story_tasks (ONE doc per story, containing tasks)
    """
    if settings.RAG_MODE.lower() == "off":
        raise HTTPException(status_code=403, detail="RAG_MODE=off — ingestion disabled")

    req_row = db.query(RequirementORM).filter_by(run_id=run_id).first()
    req_title = (req_row.title or "").strip() if req_row else ""
    req_desc = (req_row.description or "").strip() if req_row else ""
    run_embed_text = "\n\n".join([t for t in [req_title, req_desc] if t]).strip()

    # Pull experiment label / prompt mode from manifest so retrieval filters match planning
    mf = db.query(RunManifestORM).filter_by(run_id=run_id).first()
    mf_data = dict(mf.data or {}) if mf and getattr(mf, "data", None) else {}
    exp_label = mf_data.get("experiment_label")
    prompt_mode = mf_data.get("prompt_context_mode")

    pv_row = db.query(ProductVisionORM).filter_by(run_id=run_id).first()
    ts_row = db.query(TechnicalSolutionORM).filter_by(run_id=run_id).first()

    epics = (
        db.query(EpicORM)
        .filter(EpicORM.run_id == run_id)
        .order_by(EpicORM.priority_rank.asc())
        .all()
    )
    stories = (
        db.query(StoryORM)
        .filter(StoryORM.run_id == run_id)
        .order_by(StoryORM.epic_id.asc(), StoryORM.priority_rank.asc())
        .all()
    )
    tasks = (
        db.query(TaskORM)
        .filter(TaskORM.run_id == run_id)
        .order_by(TaskORM.story_id.asc(), TaskORM.order.asc())
        .all()
    )

    import json, uuid

    def _meta(doc_type: str, title: str, **extra: str) -> dict[str, str]:
        m: dict[str, str] = {
            "run_id": str(run_id),
            "type": str(doc_type),
            "title": str(title),
            "req_title": str(req_title),
            "phase": "planning",
        }
        if exp_label:
            m["experiment_label"] = str(exp_label)
        if prompt_mode:
            m["prompt_context_mode"] = str(prompt_mode)
        for k, v in extra.items():
            m[str(k)] = str(v)
        return m

    docs: list[MemoryDoc] = []

    # --- PV exemplar ---
    if pv_row and pv_row.data:
        pv_text = json.dumps(pv_row.data, indent=2, ensure_ascii=False)
        docs.append(
            MemoryDoc(
                id=f"{run_id}:product_vision:{uuid.uuid4().hex[:8]}",
                text=pv_text,
                meta=_meta(
                    "product_vision",
                    f"{req_title} — Product Vision" if req_title else "Product Vision",
                ),
                embed_text=run_embed_text,
            )
        )

    # --- TS exemplar ---
    if ts_row and ts_row.data:
        ts_text = json.dumps(ts_row.data, indent=2, ensure_ascii=False)
        docs.append(
            MemoryDoc(
                id=f"{run_id}:technical_solution:{uuid.uuid4().hex[:8]}",
                text=ts_text,
                meta=_meta(
                    "technical_solution",
                    f"{req_title} — Technical Solution" if req_title else "Technical Solution",
                ),
                embed_text=run_embed_text,
            )
        )

    # --- RA plan exemplar (bundle) ---
    if epics or stories:
        bundle = []
        stories_by_epic: dict[str, list[StoryORM]] = {}
        for s in stories:
            stories_by_epic.setdefault(s.epic_id, []).append(s)

        for e in epics:
            bundle.append({
                "epic": {
                    "id": str(e.id),
                    "title": e.title,
                    "description": e.description or "",
                    "priority_rank": int(e.priority_rank or 1),
                },
                "stories": [
                    {
                        "id": str(s.id),
                        "title": s.title,
                        "description": s.description or "",
                        "priority_rank": int(s.priority_rank or 1),
                    }
                    for s in stories_by_epic.get(e.id, [])
                ],
            })

        ra_text = json.dumps({"epics_and_stories": bundle}, indent=2, ensure_ascii=False)
        docs.append(
            MemoryDoc(
                id=f"{run_id}:ra_plan:{uuid.uuid4().hex[:8]}",
                text=ra_text,
                meta=_meta(
                    "ra_plan",
                    f"{req_title} — Epics & Stories (RA Plan)" if req_title else "RA Plan",
                ),
                embed_text=run_embed_text,
            )
        )

    # --- Story tasks exemplars (ONE per story) ---
    tasks_by_story: dict[str, list[TaskORM]] = {}
    for t in tasks:
        tasks_by_story.setdefault(t.story_id, []).append(t)

    for s in stories:
        s_tasks = tasks_by_story.get(s.id, [])
        if not s_tasks:
            continue
        st_obj = {
            "story": {
                "id": str(s.id),
                "title": s.title,
                "description": s.description or "",
            },
            "tasks": [
                {
                    "id": str(t.id),
                    "title": t.title,
                    "description": getattr(t, "description", "") or "",
                    "definition_of_done": getattr(t, "definition_of_done", None),
                    "order": getattr(t, "order", None),
                }
                for t in s_tasks
            ],
        }
        st_text = json.dumps(st_obj, indent=2, ensure_ascii=False)
        docs.append(
            MemoryDoc(
                id=f"{run_id}:story_tasks:{s.id}:{uuid.uuid4().hex[:6]}",
                text=st_text,
                meta=_meta(
                    "story_tasks",
                    f"{req_title} — {s.title} — Story Tasks" if req_title else f"{s.title} — Story Tasks",
                    story_id=str(s.id),
                    story_title=str(s.title),
                ),
                embed_text="\n\n".join([t for t in [(s.title or "").strip(), (s.description or "").strip()] if t]).strip(),
            )
        )

    if not docs:
        return {"ok": True, "added": 0, "detail": "no artefacts found to commit"}

    store = request.app.state.memory
    deleted_total = 0
    for d in docs:
        where: dict = {"type": d.meta["type"], "phase": "planning"}
        # NOTE: don't pin to run_id so exemplars can generalize across runs
        if d.meta["type"] == "story_tasks":
            where["story_id"] = d.meta["story_id"]
        deleted_total += int(store.delete_where(where))

    store.add(docs)
    return {"ok": True, "added": len(docs), "deleted": deleted_total}

@router.post("/runs/{run_id}/retrospective/commit-feedback-exemplars")
def commit_feedback_exemplars(
    run_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings = Depends(get_settings),
):
    """
    Commit *feedback-as-exemplars* into the RAG store at the same artefact levels the planner retrieves.
    Stores FEEDBACK ONLY in MemoryDoc.text, and uses requirement/story text as embed_text.
    """
    if settings.RAG_MODE.lower() == "off":
        raise HTTPException(status_code=403, detail="RAG_MODE=off — ingestion disabled")

    # Requirement used for titles + similarity queries
    req_row = db.query(RequirementORM).filter_by(run_id=run_id).first()
    req_title = (req_row.title or "").strip() if req_row else ""
    req_desc = (req_row.description or "").strip() if req_row else ""
    run_embed_text = "\n\n".join([t for t in [req_title, req_desc] if t]).strip()

    # Use manifest tags so retrieval filters match planning
    mf = db.query(RunManifestORM).filter_by(run_id=run_id).first()
    mf_data = dict(mf.data or {}) if mf and getattr(mf, "data", None) else {}
    exp_label = mf_data.get("experiment_label")
    prompt_mode = mf_data.get("prompt_context_mode")

    import uuid

    def _meta(doc_type: str, title: str, **extra: str) -> dict[str, str]:
        m: dict[str, str] = {
            "run_id": str(run_id),
            "type": str(doc_type),
            "title": str(title),
            "req_title": str(req_title),
            "phase": "planning",
        }
        if exp_label:
            m["experiment_label"] = str(exp_label)
        if prompt_mode:
            m["prompt_context_mode"] = str(prompt_mode)
        for k, v in extra.items():
            m[str(k)] = str(v)
        return m

    def _plan_fb(kind: str, story_id: str | None = None) -> str:
        row = (
            db.query(PlanArtifactFeedbackORM)
            .filter_by(run_id=run_id, kind=kind, story_id=story_id)
            .first()
        )
        ai = (row.feedback_ai or "").strip() if row else ""
        human = (row.feedback_human or "").strip() if row else ""
        return ai or human

    docs: list[MemoryDoc] = []

    # --- PV (feedback only) ---
    pv_fb = _plan_fb("product_vision", None)
    if pv_fb:
        docs.append(MemoryDoc(
            id=f"{run_id}:product_vision:{uuid.uuid4().hex[:8]}",
            text=pv_fb,
            meta=_meta("product_vision", f"{req_title} — Product Vision" if req_title else "Product Vision"),
            embed_text=run_embed_text,
        ))

    # --- TS (feedback only) ---
    ts_fb = _plan_fb("technical_solution", None)
    if ts_fb:
        docs.append(MemoryDoc(
            id=f"{run_id}:technical_solution:{uuid.uuid4().hex[:8]}",
            text=ts_fb,
            meta=_meta("technical_solution", f"{req_title} — Technical Solution" if req_title else "Technical Solution"),
            embed_text=run_embed_text,
        ))

    # --- RA plan (feedback only) ---
    ra_fb = _plan_fb("ra_plan", None)
    if ra_fb:
        docs.append(MemoryDoc(
            id=f"{run_id}:ra_plan:{uuid.uuid4().hex[:8]}",
            text=ra_fb,
            meta=_meta("ra_plan", f"{req_title} — Epics & Stories (RA Plan)" if req_title else "RA Plan"),
            embed_text=run_embed_text,
        ))

    # --- story_tasks (per story feedback only) ---
    stories = (
        db.query(StoryORM)
        .filter(StoryORM.run_id == run_id)
        .order_by(StoryORM.epic_id.asc(), StoryORM.priority_rank.asc())
        .all()
    )

    for s in stories:
        sid = str(s.id)
        fb = _plan_fb("story_tasks", sid)
        if not fb:
            continue

        story_embed = "\n\n".join(
            [t for t in [(s.title or "").strip(), (s.description or "").strip()] if t]
        ).strip() or run_embed_text

        docs.append(MemoryDoc(
            id=f"{run_id}:story_tasks:{sid}:{uuid.uuid4().hex[:6]}",
            text=fb,
            meta=_meta(
                "story_tasks",
                f"{req_title} — {s.title} — Story Tasks" if req_title else f"{s.title} — Story Tasks",
                story_id=sid,
                story_title=str(s.title),
            ),
            embed_text=story_embed,
        ))

    if not docs:
        return {"ok": True, "added": 0, "detail": "no feedback found to commit"}

    # Overwrite exemplar set (global, not pinned to run_id)
    store = request.app.state.memory
    deleted_total = 0
    for d in docs:
        where: dict = {"type": d.meta["type"], "phase": "planning"}
        if d.meta["type"] == "story_tasks":
            where["story_id"] = d.meta["story_id"]
        deleted_total += int(store.delete_where(where))

    store.add(docs)
    return {"ok": True, "added": len(docs), "deleted": deleted_total}

@router.patch("/runs/{run_id}/plan-feedback/{kind}")
def patch_plan_feedback(
    run_id: str,
    kind: PlanKind,
    body: PlanFeedbackIn,
    db: Session = Depends(get_db),
):
    story_id = body.story_id if kind == "story_tasks" else None
    if kind == "story_tasks" and not story_id:
        raise HTTPException(status_code=400, detail="story_id is required for kind=story_tasks")

    row = _get_or_create_plan_feedback(db, run_id=run_id, kind=kind, story_id=story_id)

    if body.human is not None:
        row.feedback_human = body.human.strip()
    if body.ai is not None:
        row.feedback_ai = body.ai.strip()

    db.add(row); db.commit(); db.refresh(row)
    return {"ok": True, "kind": kind, "story_id": story_id, "human": row.feedback_human, "ai": row.feedback_ai}

@router.post("/runs/{run_id}/plan-feedback/{kind}/ai")
def synthesize_plan_ai_feedback(
    run_id: str,
    kind: PlanKind,
    body: PlanAIFeedbackIn,
    db: Session = Depends(get_db),
):
    story_id = body.story_id if kind == "story_tasks" else None
    if kind == "story_tasks" and not story_id:
        raise HTTPException(status_code=400, detail="story_id is required for kind=story_tasks")

    row = _get_or_create_plan_feedback(db, run_id=run_id, kind=kind, story_id=story_id)

    context_block = _build_plan_context(db, run_id=run_id, kind=kind, story_id=story_id)

    ai_text, model_used = generate_ai_feedback_from_context(
        db,
        run_id=run_id,
        kind=kind,
        context_block=context_block,
        human_feedback=(body.human_override or row.feedback_human),
        story_id=story_id,
        metadata={"kind": kind, "story_id": story_id} if story_id else {"kind": kind},
    )

    row.feedback_ai = ai_text
    db.add(row); db.commit(); db.refresh(row)
    return {"ok": True, "ai": row.feedback_ai, "model": model_used}

@router.get("/runs/{run_id}/plan-feedback/{kind}")
def get_plan_feedback(
    run_id: str,
    kind: PlanKind,
    story_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    effective_story_id = story_id if kind == "story_tasks" else None
    if kind == "story_tasks" and not effective_story_id:
        raise HTTPException(status_code=400, detail="story_id is required for kind=story_tasks")

    row = (
        db.query(PlanArtifactFeedbackORM)
        .filter_by(run_id=run_id, kind=kind, story_id=effective_story_id)
        .first()
    )

    updated = getattr(row, "updated_at", None) if row else None

    return {
        "ok": True,
        "kind": kind,
        "story_id": effective_story_id,
        "human": (row.feedback_human or "") if row else "",
        "ai": (row.feedback_ai or "") if row else "",
        "updated_at": updated.isoformat() if updated else None,
    }