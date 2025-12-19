from __future__ import annotations
from typing import List, Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel, Field
from app.configs.settings import get_settings
from app.core.memory import MemoryDoc  # safe; no circular import

from sqlalchemy.orm import Session
from app.storage.db import get_db              # same dep you use elsewhere
from app.storage.models import RequirementORM, RunManifestORM, ProductVisionORM, TechnicalSolutionORM, EpicORM, StoryORM, TaskORM, PlanArtifactFeedbackORM

router = APIRouter(prefix="/memory", tags=["memory"])

class ArtifactIn(BaseModel):
    # Anything ingested is treated as an exemplar; types must match retrieval filters.
    type: Literal[
        "requirement",
        "product_vision",
        "technical_solution",
        "ra_plan",
        "qa_spec",
        "design_notes",
        "story_tasks",
    ]
    title: Optional[str] = None
    story_id: Optional[str] = None
    text: str = Field(min_length=1)

class IngestRequest(BaseModel):
    run_id: str
    artifacts: List[ArtifactIn]

@router.get("/config")
def get_config(settings = Depends(get_settings)):
    return {
        "mode": settings.RAG_MODE,
        "collection": settings.RAG_COLLECTION,
        "top_k": settings.RAG_TOP_K,
    }

@router.post("/ingest")
def ingest(req: IngestRequest, request: Request, settings = Depends(get_settings), db: Session = Depends(get_db)):
    if settings.RAG_MODE.lower() == "off":
        raise HTTPException(status_code=403, detail="RAG_MODE=off — ingestion disabled")
    if not req.artifacts:
        return {"ok": True, "added": 0}
    
    # fetch requirement title once
    req_row = db.query(RequirementORM).filter_by(run_id=req.run_id).first()
    req_title = (req_row.title or "").strip() if req_row else ""
    req_desc = (req_row.description or "").strip() if req_row else ""
    run_embed_text = "\n\n".join([t for t in [req_title, req_desc] if t]).strip()

    import uuid
    docs: List[MemoryDoc] = []
    deleted_total = 0

    store = request.app.state.memory
    for a in req.artifacts:
        # ---------- Title ----------
        if req_title:
            if a.type == "product_vision":
                title = f"{req_title} — Product Vision"
            elif a.type == "technical_solution":
                title = f"{req_title} — Technical Solution"
            elif a.type == "ra_plan":
                title = f"{req_title} — Epics & Stories (RA Plan)"
            elif a.type == "qa_spec":
                title = f"{req_title} — QA Spec"
            elif a.type == "design_notes":
                title = f"{req_title} — Design Notes"
            elif a.type == "story_tasks":
                title = f"{req_title} — Story Tasks"
            else:
                title = a.title or req_title or ""
        else:
            title = a.title or ""

        # ---------- Meta ----------
        meta: dict[str, str] = {
            "run_id": str(req.run_id),
            "type": str(a.type),
            "title": str(title),
            "req_title": str(req_title),
            "phase": "planning",
        }

        mf = db.query(RunManifestORM).filter_by(run_id=req.run_id).first()
        mf_data = dict(mf.data or {}) if mf and getattr(mf, "data", None) else {}

        exp_label = mf_data.get("experiment_label") or getattr(settings, "EXPERIMENT_LABEL", None)
        if exp_label:
            meta["experiment_label"] = str(exp_label)

        prompt_mode = mf_data.get("prompt_context_mode") or getattr(settings, "PROMPT_CONTEXT_MODE", "structured")
        meta["prompt_context_mode"] = str(prompt_mode)

        # story_tasks requires story_id
        if a.type == "story_tasks":
            if not a.story_id:
                raise HTTPException(status_code=400, detail="story_id is required for type=story_tasks")
            meta["story_id"] = str(a.story_id)

        # ---------- EMBED TEXT ----------
        # Similarity should match on requirement/story description, NOT on feedback payload.
        embed_text = run_embed_text
        if a.type == "story_tasks":
            s = db.get(StoryORM, a.story_id)
            if s:
                embed_text = "\n\n".join(
                    [t for t in [(s.title or "").strip(), (s.description or "").strip()] if t]
                ).strip() or run_embed_text

        # ---------- OVERWRITE (per-run) ----------
        where: dict = {
            "run_id": str(req.run_id),
            "type": meta["type"],
        }
        if meta["type"] == "story_tasks":
            where["story_id"] = meta["story_id"]

        try:
            deleted_total += int(store.delete_where(where))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"delete_where failed: {e}")

        # ---------- Append doc (ALWAYS) ----------
        docs.append(
            MemoryDoc(
                id=f"{req.run_id}:{a.type}:{uuid.uuid4().hex[:8]}",
                text=a.text,                 # <- FEEDBACK PAYLOAD (what gets injected)
                meta=meta,
                embed_text=embed_text,       # <- MATCHING SIGNAL (what gets embedded)
            )
        )

    store.add(docs)
    return {"ok": True, "deleted": deleted_total, "added": len(docs)}

@router.post("/purge")
def purge(request: Request, settings = Depends(get_settings)):
    # Allow only in debug/dev
    if not getattr(settings, "DEBUG", False):
        raise HTTPException(status_code=403, detail="Purge allowed only when DEBUG=true")
    request.app.state.memory.purge()
    return {"ok": True}

@router.get("/status")
def rag_status(request: Request, settings = Depends(get_settings)):
    store = request.app.state.memory
    return {
        "mode": settings.RAG_MODE,
        "collection": settings.RAG_COLLECTION,
        "top_k": settings.RAG_TOP_K,
        "use_rag": settings.USE_RAG,
        "store": type(store).__name__,
        # NEW: experiment-related knobs (for UI + sanity checks)
        "experiment_label": getattr(settings, "EXPERIMENT_LABEL", None),
        "prompt_context_mode": getattr(settings, "PROMPT_CONTEXT_MODE", "structured"),
    }

@router.get("/search")
def dev_search(request: Request, q: str = Query(...)):
    hits = request.app.state.memory.search(q, top_k=5)
    return [{"id": h.id, "meta": h.meta, "text": h.text[:160]} for h in hits]

@router.post("/ingest-from-run")
def ingest_from_run(
    run_id: str,
    request: Request,
    settings = Depends(get_settings),
    db: Session = Depends(get_db),
):
    """
    Ingest "approved" artefacts from a run into vector memory as EXEMPLARS
    at the same levels planning retrieves:
      - product_vision
      - technical_solution
      - ra_plan
      - story_tasks (one doc per story, for better matching)
    """
    if settings.RAG_MODE.lower() == "off":
        raise HTTPException(status_code=403, detail="RAG_MODE=off — ingestion disabled")

    import json, uuid

    # Requirement title (for better titles / retrieval)
    req_row = db.query(RequirementORM).filter_by(run_id=run_id).first()
    req_title = (req_row.title if req_row else "") or ""
    req_desc = (req_row.description or "").strip() if req_row else ""
    run_embed_text = "\n\n".join([t for t in [req_title, req_desc] if t]).strip()

    # Run manifest tags (must match planning retrieval filters)
    mf = db.query(RunManifestORM).filter_by(run_id=run_id).first()
    mf_data = dict(mf.data or {}) if mf and getattr(mf, "data", None) else {}
    exp_label = mf_data.get("experiment_label") or getattr(settings, "EXPERIMENT_LABEL", None)
    prompt_mode = mf_data.get("prompt_context_mode") or getattr(settings, "PROMPT_CONTEXT_MODE", "structured")

    def _plan_feedback(kind: str, story_id: str | None = None) -> str:
        row = (
            db.query(PlanArtifactFeedbackORM)
            .filter_by(run_id=run_id, kind=kind, story_id=story_id)
            .first()
        )
        ai = (row.feedback_ai or "").strip() if row else ""
        human = (row.feedback_human or "").strip() if row else ""
        return ai or human

    def _meta(doc_type: str, title: str, extra: dict[str, str] | None = None) -> dict[str, str]:
        m: dict[str, str] = {
            "run_id": str(run_id),
            "type": str(doc_type),
            "title": str(title),
            "req_title": str(req_title),
            "phase": "planning",
            "prompt_context_mode": str(prompt_mode),
        }
        if exp_label:
            m["experiment_label"] = str(exp_label)
        if extra:
            for k, v in extra.items():
                m[str(k)] = str(v)
        return m

    docs: list[MemoryDoc] = []

    # ---- PV exemplar ----

    pv_fb = _plan_feedback("product_vision", None)
    if pv_fb:
        docs.append(MemoryDoc(
            id=f"{run_id}:product_vision:{uuid.uuid4().hex[:8]}",
            text=pv_fb,
            meta=_meta("product_vision", f"{req_title} — Product Vision".strip(" —")),
            embed_text=run_embed_text,
        ))

    # ---- TS exemplar ----

    ts_fb = _plan_feedback("technical_solution", None)
    if ts_fb:
        docs.append(MemoryDoc(
            id=f"{run_id}:technical_solution:{uuid.uuid4().hex[:8]}",
            text=ts_fb,
            meta=_meta("technical_solution", f"{req_title} — Technical Solution".strip(" —")),
            embed_text=run_embed_text,
        ))

    # ---- RA plan exemplar (epics + stories) ----

    ra_fb = _plan_feedback("ra_plan", None)
    if ra_fb:
        docs.append(MemoryDoc(
            id=f"{run_id}:ra_plan:{uuid.uuid4().hex[:8]}",
            text=ra_fb,
            meta=_meta("ra_plan", f"{req_title} — Epics & Stories (RA Plan)".strip(" —")),
            embed_text=run_embed_text,
        ))

    # ---- Story tasks exemplars (one per story, feedback-only) ----
    stories = (
        db.query(StoryORM)
        .filter(StoryORM.run_id == run_id)
        .order_by(StoryORM.epic_id.asc(), StoryORM.priority_rank.asc())
        .all()
    )

    for s in stories:
        sid = str(s.id)
        fb = _plan_feedback("story_tasks", sid)
        if not fb:
            continue

        story_embed = "\n\n".join(
            [t for t in [(s.title or "").strip(), (s.description or "").strip()] if t]
        ).strip() or run_embed_text

        title = f"{req_title} — Story Tasks — {s.title}".strip(" —")
        docs.append(MemoryDoc(
            id=f"{run_id}:story_tasks:{sid}:{uuid.uuid4().hex[:8]}",
            text=fb,
            meta=_meta("story_tasks", title, extra={"story_id": sid}),
            embed_text=story_embed,
        ))

    store = request.app.state.memory

    deleted_total = 0
    for d in docs:
        where: dict = {
            "run_id": str(run_id),
            "type": d.meta["type"],
        }
        if d.meta["type"] == "story_tasks":
            where["story_id"] = d.meta["story_id"]

        try:
            deleted_total += int(store.delete_where(where))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"delete_where failed: {e}")

    store.add(docs)
    return {"ok": True, "deleted": deleted_total, "added": len(docs)}
