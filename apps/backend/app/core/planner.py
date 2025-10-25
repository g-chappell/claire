from __future__ import annotations
from typing import Any, Dict, Optional, Literal

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from app.core.models import (
    PlanBundle, ProductVision, TechnicalSolution, Epic, Story,
    AcceptanceCriteria, Requirement, Task, DesignNote
)

from app.storage.models import (
    RequirementORM, ProductVisionORM, TechnicalSolutionORM,
    EpicORM, StoryORM, AcceptanceORM, TaskORM, DesignNoteORM
)
from app.agents.meta.product_manager_llm import ProductManagerLLM

Priority = Literal["Must", "Should", "Could"]

def _coerce_priority(p: Optional[str]) -> Priority:
    s = (p or "Should").strip().lower()
    if s.startswith("must"):
        return "Must"
    if s.startswith("could"):
        return "Could"
    return "Should"

pm = ProductManagerLLM()

# --- NEW: persist only PV/TS (used by the stage 1 gate) ---
def _persist_vision_solution(db: Session, run_id: str,
                             vision: ProductVision,
                             solution: TechnicalSolution) -> None:
    db.merge(ProductVisionORM(run_id=run_id, data=vision.model_dump()))
    db.merge(TechnicalSolutionORM(run_id=run_id, data=solution.model_dump()))
    db.commit()


# --- NEW: stage 1 - generate PV/TS only ---
def generate_vision_solution(db: Session, run_id: str, rag_context: str | None = None,) -> tuple[ProductVision, TechnicalSolution]:
    """Run Vision + Architecture chains and persist only those results."""
    req: RequirementORM | None = (
        db.query(RequirementORM)
        .filter(RequirementORM.run_id == run_id)
        .order_by(RequirementORM.id.asc())
        .first()
    )
    if not req:
        raise ValueError("requirement not found for run")
    
    # If RAG is enabled upstream, inject context into the description so
    # downstream prompt builders can reuse it without any other changes.
    combined_desc = req.description or ""
    if rag_context:
        combined_desc = (
        combined_desc.rstrip() + "\n\nYou may reuse relevant items from prior approved artefacts:\n" + rag_context + "\n\nIf irrelevant, ignore them.")

    p_req = Requirement(
        id=req.id,
        title=req.title,
        description=combined_desc,
        constraints=req.constraints or [],
        priority=_coerce_priority(getattr(req, "priority", None)),
        non_functionals=req.non_functionals or [],
    )

    pv, ts = pm.plan_vision_solution(p_req.model_dump())
    _persist_vision_solution(db, run_id, pv, ts)
    return pv, ts


# --- NEW: stage 2 - finalise the plan from PV/TS (plus optional overrides) ---
def finalise_plan(db: Session, run_id: str,
                  vision_override: dict | None = None,
                  solution_override: dict | None = None) -> PlanBundle:
    """
    Produce epics, stories, acceptance, tasks, and design notes using the
    currently stored PV/TS, optionally applying overrides from the request.
    """
    # Load PV/TS (or use provided overrides)
    pv_row = db.query(ProductVisionORM).filter_by(run_id=run_id).first()
    ts_row = db.query(TechnicalSolutionORM).filter_by(run_id=run_id).first()

    if not pv_row and not vision_override:
        raise ValueError("product vision not found for run")
    if not ts_row and not solution_override:
        raise ValueError("technical solution not found for run")

    pv_data: Optional[dict] = None
    ts_data: Optional[dict] = None

    if vision_override is not None:
        pv_data = vision_override
    elif pv_row is not None:
        pv_data = pv_row.data

    if solution_override is not None:
        ts_data = solution_override
    elif ts_row is not None:
        ts_data = ts_row.data

    if pv_data is None:
        raise ValueError("product vision not found for run")
    if ts_data is None:
        raise ValueError("technical solution not found for run")

    pv = ProductVision(**pv_data)
    ts = TechnicalSolution(**ts_data)

    # Load requirement (same source used by plan_run)
    req: RequirementORM | None = (
        db.query(RequirementORM)
        .filter(RequirementORM.run_id == run_id)
        .order_by(RequirementORM.id.asc())
        .first()
    )
    if not req:
        raise ValueError("requirement not found for run")

    p_req = Requirement(
        id=req.id,
        title=req.title,
        description=req.description,
        constraints=req.constraints or [],
        priority=_coerce_priority(getattr(req, "priority", None)),
        non_functionals=req.non_functionals or [],
    )

    # Generate remaining artefacts and persist full bundle
    bundle = pm.plan_remaining(p_req.model_dump(), pv, ts)
    _persist_plan(db, run_id, req, bundle)
    return bundle

def _persist_plan(db: Session, run_id: str, requirement: RequirementORM, bundle: PlanBundle) -> None:
    # product vision & technical solution as JSON blobs
    db.merge(ProductVisionORM(run_id=run_id, data=bundle.product_vision.model_dump()))
    db.merge(TechnicalSolutionORM(run_id=run_id, data=bundle.technical_solution.model_dump()))

    # epics
    for e in bundle.epics:
        db.merge(EpicORM(
            id=e.id, run_id=run_id, title=e.title,
            description=e.description, priority_rank=e.priority_rank
        ))

    # stories + acceptance
    for s in bundle.stories:
        db.merge(StoryORM(
            id=s.id, run_id=run_id, requirement_id=requirement.id,
            epic_id=s.epic_id, title=s.title, description=s.description,
            priority_rank=s.priority_rank, tests=s.tests
        ))
        # clear then re-write acceptance entries
        db.query(AcceptanceORM).filter_by(run_id=run_id, story_id=s.id).delete(synchronize_session=False)
        for i, ac in enumerate(s.acceptance, start=1):
            db.merge(AcceptanceORM(
                id=f"AC-{s.id}-{i}", run_id=run_id, story_id=s.id, gherkin=ac.gherkin
            ))

    def _columns(model) -> set[str]:
        try:
            return {c.key for c in sa_inspect(model).columns}
        except Exception:
            return set(getattr(model, "__table__").columns.keys())

    task_cols = _columns(TaskORM)
    dn_cols = _columns(DesignNoteORM)

    # Tasks (clear then write)
    db.query(TaskORM).filter_by(run_id=run_id).delete(synchronize_session=False)
    for s in bundle.stories:
        for t in s.tasks:
            kwargs: Dict[str, Any] = {
            "id": t.id,
            "run_id": run_id,
            "story_id": s.id,
            "title": t.title,
        }
            if "order" in task_cols:
                kwargs["order"] = t.order
            if "status" in task_cols:
                kwargs["status"] = t.status
            db.merge(TaskORM(**kwargs))

    # Design Notes (clear then write)
    db.query(DesignNoteORM).filter_by(run_id=run_id).delete(synchronize_session=False)

    def _as_data_blob(dn: DesignNote) -> Dict[str, Any]:
        return {
            "title": dn.title,
            "kind": dn.kind,
            "body_md": dn.body_md,
            "tags": dn.tags,
            "related_epic_ids": dn.related_epic_ids,
            "related_story_ids": dn.related_story_ids,
        }

    for dn in bundle.design_notes:
        kwargs: Dict[str, Any] = {
        "id": dn.id,
        "run_id": run_id,
    }

        # Required by your current schema
        if "scope" in dn_cols:
            kwargs["scope"] = "run"  # run-scoped note

        # Prefer column-by-column if present
        if "title" in dn_cols:
            kwargs["title"] = dn.title
        if "body_md" in dn_cols:
            kwargs["body_md"] = dn.body_md
        if "kind" in dn_cols:
            kwargs["kind"] = dn.kind
        if "tags" in dn_cols:
            kwargs["tags"] = dn.tags
        if "related_epic_ids" in dn_cols:
            kwargs["related_epic_ids"] = dn.related_epic_ids
        if "related_story_ids" in dn_cols:
            kwargs["related_story_ids"] = dn.related_story_ids

         # If your ORM stores solution context on design_notes, populate it
        if "decisions" in dn_cols:
            kwargs["decisions"] = bundle.technical_solution.decisions or []
        if "interfaces" in dn_cols:
            kwargs["interfaces"] = bundle.technical_solution.interfaces or {}

        # If this table uses a single JSON blob (e.g. 'data') and
        # does NOT have the first-class columns above, store the note there.
        if "data" in dn_cols and not any(
            c in dn_cols for c in ("title","body_md","kind","tags","related_epic_ids","related_story_ids")
        ):
            kwargs["data"] = _as_data_blob(dn)

        db.merge(DesignNoteORM(**kwargs))

    db.commit()

def plan_run(db: Session, run_id: str) -> PlanBundle:
    req: RequirementORM | None = (
        db.query(RequirementORM)
        .filter(RequirementORM.run_id == run_id)
        .order_by(RequirementORM.id.asc())
        .first()
    )
    if not req:
        raise ValueError("requirement not found for run")

    p_req = Requirement(
        id=req.id, title=req.title, description=req.description,
        constraints=req.constraints or [], priority=_coerce_priority(getattr(req, "priority", None)),
        non_functionals=req.non_functionals or [],
    )

    bundle = pm.plan(p_req.model_dump())
    _persist_plan(db, run_id, req, bundle)
    return bundle

def read_plan(db: Session, run_id: str) -> PlanBundle:
    pv = db.query(ProductVisionORM).filter_by(run_id=run_id).first()
    ts = db.query(TechnicalSolutionORM).filter_by(run_id=run_id).first()
    if not pv or not ts:
        raise ValueError("plan not found for run")

    # ---- Epics & Stories
    epics_orm = (
        db.query(EpicORM)
        .filter_by(run_id=run_id)
        .order_by(EpicORM.priority_rank.asc())
        .all()
    )
    stories_orm = (
        db.query(StoryORM)
        .filter_by(run_id=run_id)
        .order_by(StoryORM.epic_id, StoryORM.priority_rank.asc())
        .all()
    )

    # Acceptance by story
    ac_rows = db.query(AcceptanceORM).filter_by(run_id=run_id).all()
    ac_by_story: dict[str, list[AcceptanceCriteria]] = {}
    for r in ac_rows:
        ac_by_story.setdefault(r.story_id, []).append(
            AcceptanceCriteria(story_id=r.story_id, gherkin=r.gherkin)
        )

    epics = [
        Epic(
            id=e.id,
            title=e.title,
            description=e.description,
            priority_rank=e.priority_rank,
        )
        for e in epics_orm
    ]

    stories = [
        Story(
            id=s.id,
            epic_id=s.epic_id,
            title=s.title,
            description=s.description,
            priority_rank=s.priority_rank or 1,
            acceptance=ac_by_story.get(s.id, []),
            tests=s.tests or [],
        )
        for s in stories_orm
    ]

    # ---- Tasks by story
    task_rows = db.query(TaskORM).filter_by(run_id=run_id).all()
    tasks_by_story: dict[str, list[Task]] = {}
    for tr in task_rows:
        tasks_by_story.setdefault(tr.story_id, []).append(
            Task(
                id=tr.id,
                story_id=tr.story_id,
                title=tr.title,
                order=getattr(tr, "order", 1),
                status=getattr(tr, "status", "todo"),
            )
        )
    for s in stories:
        s.tasks = sorted(tasks_by_story.get(s.id, []), key=lambda t: t.order)

    # ---- Design notes (handle both columnized and JSON-blob tables)
    dn_cols = {c.key for c in sa_inspect(DesignNoteORM).columns}
    dn_rows = db.query(DesignNoteORM).filter_by(run_id=run_id).all()
    design_notes: list[DesignNote] = []

    def _from_data_blob(r) -> DesignNote:
        data = getattr(r, "data", {}) or {}
        return DesignNote(
            id=r.id,
            title=data.get("title", "Design note"),
            kind=data.get("kind", "other"),
            body_md=data.get("body_md", ""),
            tags=data.get("tags", []),
            related_epic_ids=data.get("related_epic_ids", []),
            related_story_ids=data.get("related_story_ids", []),
        )

    for r in dn_rows:
        if "data" in dn_cols and getattr(r, "data", None):
            note = _from_data_blob(r)
        else:
            # Column-by-column with safe defaults
            title = getattr(r, "title", None) or "Design note"
            kind = getattr(r, "kind", None) or "other"
            body_md = getattr(r, "body_md", None) or ""
            tags = getattr(r, "tags", None) or []
            related_epic_ids = getattr(r, "related_epic_ids", None) or []
            related_story_ids = getattr(r, "related_story_ids", None) or []
            note = DesignNote(
                id=r.id,
                title=title,
                kind=kind,
                body_md=body_md,
                tags=tags,
                related_epic_ids=related_epic_ids,
                related_story_ids=related_story_ids,
            )
        design_notes.append(note)

    design_notes.sort(key=lambda dn: (dn.kind, dn.title.lower()))

    return PlanBundle(
        product_vision=ProductVision(**pv.data),
        technical_solution=TechnicalSolution(**ts.data),
        epics=epics,
        stories=stories,
        design_notes=design_notes,
    )
