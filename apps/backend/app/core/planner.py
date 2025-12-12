from __future__ import annotations
from typing import Any, Dict, Optional, Literal, cast

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from app.core.models import (
    PlanBundle,
    ProductVision,
    TechnicalSolution,
    Epic,
    Story,
    AcceptanceCriteria,
    Requirement,
    Task,
    DesignNote,
    RunManifest,
)

from app.storage.models import (
    RequirementORM,
    ProductVisionORM,
    TechnicalSolutionORM,
    EpicORM,
    StoryORM,
    AcceptanceORM,
    TaskORM,
    DesignNoteORM,
    RunManifestORM,
)

from app.configs.settings import get_settings

from app.agents.meta.product_manager_llm import ProductManagerLLM

import logging
logger = logging.getLogger(__name__)

Priority = Literal["Must", "Should", "Could"]

def _coerce_priority(p: Optional[str]) -> Priority:
    s = (p or "Should").strip().lower()
    if s.startswith("must"):
        return "Must"
    if s.startswith("could"):
        return "Could"
    return "Should"

TaskStatus = Literal["todo", "doing", "done"]

def _coerce_task_status(v) -> TaskStatus:
    s = str(v or "todo").lower()
    if s not in ("todo", "doing", "done"):
        s = "todo"
    return cast(TaskStatus, s)

pm = ProductManagerLLM()

# --- helpers ---------------------------------------------------------------

def _get_run_config(db: Session, run_id: str) -> RunManifest:
    """
    Resolve per-run config snapshot (manifest) with env defaults as fallback.
    This is what the planner should use so experiments are repeatable.
    """
    settings = get_settings()

    mf: RunManifestORM | None = (
        db.query(RunManifestORM).filter_by(run_id=run_id).first()
    )
    data: dict[str, Any] = dict(mf.data or {}) if mf and getattr(mf, "data", None) else {}

    cfg = RunManifest(
        run_id=run_id,
        model=data.get("model", settings.LLM_MODEL),
        provider=data.get("provider", settings.LLM_PROVIDER),
        temperature=data.get("temperature", settings.TEMPERATURE),
        context_snapshot_id=data.get("context_snapshot_id", ""),
        experiment_label=data.get("experiment_label", settings.EXPERIMENT_LABEL),
        prompt_context_mode=data.get("prompt_context_mode", settings.PROMPT_CONTEXT_MODE),
        use_rag=data.get("use_rag", settings.USE_RAG),
    )

    logger.info(
        "RUN_CONFIG run=%s provider=%s model=%s temp=%s exp=%s mode=%s use_rag=%s ctx_id=%s",
        cfg.run_id,
        cfg.provider,
        cfg.model,
        cfg.temperature,
        cfg.experiment_label,
        cfg.prompt_context_mode,
        cfg.use_rag,
        cfg.context_snapshot_id,
    )

    return cfg

def _columns(model) -> set[str]:
    """Return the set of column names for an ORM model (works with Alembic/autogen too)."""
    try:
        return {c.key for c in sa_inspect(model).columns}
    except Exception:
        # Fallback for unusual table declarations
        return set(getattr(model, "__table__").columns.keys())
    
# --- Dependency ordering helpers --------------------------------------------

from collections import defaultdict, deque

def _validate_llm_order(bundle: PlanBundle) -> None:
    """
    Enforce that the LLM provides complete ordering + true prerequisites.
    We do not sort or mutate anything here — we only validate and fail fast.
    Rules:
      • All epics/stories must have positive, unique priority_rank (per epic for stories).
      • For any item with rank > 1, depends_on MUST be non-empty and reference earlier items only.
      • Story dependencies must stay within the same epic.
    """
    # ---- Epics ----
    epic_ids = [e.id for e in bundle.epics]
    rank_by_epic = {e.id: int(getattr(e, "priority_rank", 0) or 0) for e in bundle.epics}
    epic_ranks = list(rank_by_epic.values())

    for e in bundle.epics:
        r = rank_by_epic[e.id]
        if r <= 0:
            raise ValueError(f"LLM must set positive priority_rank for epic {e.id}")
        deps = list(getattr(e, "depends_on", []) or [])
        # If not first in order, must depend on at least one earlier epic
        if r > 1 and not deps:
            raise ValueError(f"Epic {e.id} (rank {r}) must declare depends_on one or more earlier epics")
        for dep in deps:
            if dep not in epic_ids:
                raise ValueError(f"Epic {e.id} depends_on unknown epic id '{dep}'")
            if dep == e.id:
                raise ValueError(f"Epic {e.id} cannot depend on itself")
            if rank_by_epic.get(dep, 0) >= r:
                raise ValueError(f"Epic {e.id} (rank {r}) depends_on epic {dep} with equal/greater rank")
    if len(set(epic_ranks)) != len(epic_ranks):
        raise ValueError("Duplicate epic priority_rank values are not allowed")

    # ---- Stories (validate per-epic) ----
    stories_by_epic: dict[str, list[Story]] = {}
    for s in bundle.stories:
        stories_by_epic.setdefault(s.epic_id, []).append(s)

    for epic_id, group in stories_by_epic.items():
        rank_by_story = {s.id: int(getattr(s, "priority_rank", 0) or 0) for s in group}
        sids = set(rank_by_story.keys())
        sranks = list(rank_by_story.values())

        for s in group:
            r = rank_by_story[s.id]
            if r <= 0:
                raise ValueError(f"LLM must set positive priority_rank for story {s.id} (epic {epic_id})")
            deps = list(getattr(s, "depends_on", []) or [])
            if r > 1 and not deps:
                raise ValueError(f"Story {s.id} (rank {r}, epic {epic_id}) must depend on an earlier story in the same epic")
            for dep in deps:
                if dep not in sids:
                    raise ValueError(f"Story {s.id} depends_on '{dep}' outside its epic {epic_id}")
                if dep == s.id:
                    raise ValueError(f"Story {s.id} cannot depend on itself")
                if rank_by_story.get(dep, 0) >= r:
                    raise ValueError(f"Story {s.id} (rank {r}) depends_on '{dep}' with equal/greater rank in epic {epic_id}")

        if len(set(sranks)) != len(sranks):
            raise ValueError(f"Duplicate story priority_rank values in epic {epic_id} are not allowed")


def _topo_order(nodes: list, get_id, get_deps) -> list[str]:
    """Return a stable topological order of node IDs; breaks ties by original order."""
    id_list = [get_id(n) for n in nodes]
    idx_map = {get_id(n): i for i, n in enumerate(nodes)}

    # Build graph
    deps = {get_id(n): list(dict.fromkeys(get_deps(n) or [])) for n in nodes}
    indeg = defaultdict(int)
    children = defaultdict(list)
    for nid, ds in deps.items():
        for d in ds:
            if d not in idx_map:
                # ignore unknown dependencies gracefully
                continue
            indeg[nid] += 1
            children[d].append(nid)

    # Kahn with stability (keep original order)
    q = deque(sorted([nid for nid in id_list if indeg[nid] == 0], key=lambda x: idx_map[x]))
    ordered = []
    while q:
        nid = q.popleft()
        ordered.append(nid)
        for ch in children[nid]:
            indeg[ch] -= 1
            if indeg[ch] == 0:
                q.append(ch)
        # maintain stability for tie breaks
        q = deque(sorted(q, key=lambda x: idx_map[x]))

    # If cycle, append any remaining nodes by original order
    if len(ordered) < len(id_list):
        remaining = [nid for nid in id_list if nid not in ordered]
        ordered.extend(remaining)
    return ordered


# def _apply_dependency_ordering(bundle: PlanBundle) -> PlanBundle:
#     """
#     Use depends_on to compute stable priority_rank for Epics and Stories.
#     We only fill ranks when missing or zero; if LLM provided ranks, we keep them.
#     """
#     # ---- Epics: topo order by depends_on, then assign any missing ranks ----
#     epic_order = _topo_order(
#         bundle.epics,
#         get_id=lambda e: e.id,
#         get_deps=lambda e: (getattr(e, "depends_on", []) or []),
#     )
#     if epic_order:
#         idx_map = {eid: i for i, eid in enumerate(epic_order, start=1)}
#         for e in bundle.epics:
#             if not getattr(e, "priority_rank", None) or int(getattr(e, "priority_rank") or 0) == 0:
#                 e.priority_rank = idx_map.get(e.id, e.priority_rank or 0) or 0

#     # ---- Stories: per-epic topo order, then assign any missing ranks ----
#     from collections import defaultdict
#     by_epic: dict[str, list[Story]] = defaultdict(list)
#     for s in bundle.stories:
#         by_epic[s.epic_id].append(s)

#     for epic_id, group in by_epic.items():
#         story_order = _topo_order(
#             group,
#             get_id=lambda s: s.id,
#             get_deps=lambda s: (getattr(s, "depends_on", []) or []),
#         )
#         if story_order:
#             # assign only if missing
#             rank_by_id = {sid: i for i, sid in enumerate(story_order, start=1)}
#             for s in group:
#                 if not getattr(s, "priority_rank", None) or int(getattr(s, "priority_rank") or 0) == 0:
#                     s.priority_rank = rank_by_id.get(s.id, s.priority_rank or 0) or 0

#     return bundle




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

    pv, ts = pm.plan_vision_solution(p_req.model_dump(), db=db, run_id=run_id)
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

    cfg = _get_run_config(db, run_id)
    logger.info(
        "FINALISE_PLAN_START run=%s exp=%s provider=%s model=%s mode=%s use_rag=%s",
        run_id,
        cfg.experiment_label,
        cfg.provider,
        cfg.model,
        cfg.prompt_context_mode,
        cfg.use_rag,
    )
    bundle = pm.plan_remaining(
        p_req.model_dump(),
        pv,
        ts,
        db=db,
        run_id=run_id,
        prompt_context_mode=cfg.prompt_context_mode,
    )
    _persist_plan(db, run_id, req, bundle)
    return bundle

def _persist_plan(db: Session, run_id: str, requirement: RequirementORM, bundle: PlanBundle) -> None:
    # product vision & technical solution as JSON blobs
    db.merge(ProductVisionORM(run_id=run_id, data=bundle.product_vision.model_dump()))
    db.merge(TechnicalSolutionORM(run_id=run_id, data=bundle.technical_solution.model_dump()))

    # # epics
    # if bundle.epics:
    #     # safety: only fill ranks that are still missing after dependency ordering
    #     if any(getattr(e, "priority_rank", None) in (None, 0) for e in bundle.epics):
    #         used = {
    #             int(getattr(e, "priority_rank", 0) or 0)
    #             for e in bundle.epics
    #             if getattr(e, "priority_rank", None) not in (None, 0)
    #         }
    #         next_rank = 1
    #         for e in bundle.epics:
    #             if not getattr(e, "priority_rank", None) or int(getattr(e, "priority_rank") or 0) == 0:
    #                 while next_rank in used:
    #                     next_rank += 1
    #                 e.priority_rank = next_rank
    #                 used.add(next_rank)
    epic_cols = _columns(EpicORM)
    for e in bundle.epics:
        _epic_kwargs: Dict[str, Any] = {
            "id": e.id,
            "run_id": run_id,
            "title": e.title,
            "description": e.description,
            "priority_rank": e.priority_rank,
        }
        if "depends_on" in epic_cols:
            _epic_kwargs["depends_on"] = [str(d) for d in (getattr(e, "depends_on", []) or [])]
        db.merge(EpicORM(**_epic_kwargs))

    # ---- Stories: group by epic, validate, and persist exactly as provided ----
    by_epic_for_rank: dict[str, list[Story]] = {}
    for s in bundle.stories:
        by_epic_for_rank.setdefault(s.epic_id, []).append(s)

    story_cols = _columns(StoryORM)

    for epic_id, group in by_epic_for_rank.items():
        # ensure every story has a positive, explicit priority_rank
        if any(getattr(s, "priority_rank", None) in (None, 0) for s in group):
            raise ValueError(f"LLM must provide priority_rank for all stories in epic {epic_id}")

        # persist in LLM-declared order; tie-break by title only for deterministic DB writes
        for s in sorted(group, key=lambda x: (int(getattr(x, "priority_rank")), x.title.lower())):
            _story_kwargs: Dict[str, Any] = {
                "id": s.id,
                "run_id": run_id,
                "requirement_id": requirement.id,
                "epic_id": s.epic_id,
                "title": s.title,
                "description": s.description,
            }
            if "priority_rank" in story_cols:
                _story_kwargs["priority_rank"] = int(s.priority_rank)
            if "depends_on" in story_cols:
                _story_kwargs["depends_on"] = [str(d) for d in (getattr(s, "depends_on", []) or [])]

            db.merge(StoryORM(**_story_kwargs))

            # clear then re-write acceptance entries for this story
            db.query(AcceptanceORM).filter_by(
                run_id=run_id, story_id=s.id
            ).delete(synchronize_session=False)
            for ac_idx, ac in enumerate(s.acceptance, start=1):
                db.merge(AcceptanceORM(
                    id=f"AC-{s.id}-{ac_idx}",
                    run_id=run_id,
                    story_id=s.id,
                    gherkin=ac.gherkin
                ))

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
            "title": t.title or "",
        }
            if "order" in task_cols:
                if getattr(t, "order", None) in (None, 0):
                    raise ValueError(f"LLM did not supply a valid 'order' for task '{t.title}' (story {s.id}).")
                kwargs["order"] = int(t.order)
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
        id=req.id,
        title=req.title,
        description=req.description,
        constraints=req.constraints or [],
        priority=_coerce_priority(getattr(req, "priority", None)),
        non_functionals=req.non_functionals or [],
    )

    cfg = _get_run_config(db, run_id)
    logger.info(
        "PLAN_RUN_START run=%s exp=%s provider=%s model=%s mode=%s use_rag=%s",
        run_id,
        cfg.experiment_label,
        cfg.provider,
        cfg.model,
        cfg.prompt_context_mode,
        cfg.use_rag,
    )
    bundle = pm.plan(
        p_req.model_dump(),
        db=db,
        run_id=run_id,
        prompt_context_mode=cfg.prompt_context_mode,
    )
    # bundle = _apply_dependency_ordering(bundle)
    # try:
    #     if any(getattr(e, "priority_rank", None) in (None, 0) for e in bundle.epics):
    #         logger.debug("plan_run: filled missing epic ranks after LLM output")
    #     if any(getattr(s, "priority_rank", None) in (None, 0) for s in bundle.stories):
    #         logger.debug("plan_run: filled missing story ranks after LLM output")
    # except Exception:
    #     pass
    #_validate_llm_order(bundle)
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

    epic_cols_read = {c.key for c in sa_inspect(EpicORM).columns}
    epics = []
    for e in epics_orm:
        ep_kwargs: Dict[str, Any] = {
            "id": str(getattr(e, "id")),
            "title": str(getattr(e, "title", "")),
            "description": str(getattr(e, "description", "")),
            "priority_rank": int(getattr(e, "priority_rank", 1) or 1),
        }
        if "depends_on" in epic_cols_read:
            deps = getattr(e, "depends_on", []) or []
            ep_kwargs["depends_on"] = [str(d) for d in deps]
        epics.append(Epic(**ep_kwargs))

    story_cols_read = {c.key for c in sa_inspect(StoryORM).columns}
    stories = []
    for s in stories_orm:
        st_kwargs: Dict[str, Any] = {
            "id": str(getattr(s, "id")),
            "epic_id": str(getattr(s, "epic_id")),
            "title": str(getattr(s, "title", "")),
            "description": str(getattr(s, "description", "")),
            "priority_rank": int(getattr(s, "priority_rank", 1) or 1),
            "acceptance": ac_by_story.get(str(getattr(s, "id")), []),
            "tests": [str(t) for t in (getattr(s, "tests", []) or [])],
        }
        if "depends_on" in story_cols_read:
            deps = getattr(s, "depends_on", []) or []
            st_kwargs["depends_on"] = [str(d) for d in deps]
        stories.append(Story(**st_kwargs))

    # ---- Tasks by story
    task_rows = db.query(TaskORM).filter_by(run_id=run_id).all()
    tasks_by_story: dict[str, list[Task]] = {}
    for tr in task_rows:
        sid = str(getattr(tr, "story_id"))
        tasks_by_story.setdefault(sid, []).append(
            Task(
                id=str(getattr(tr, "id")),
                story_id=sid,
                title=str(getattr(tr, "title", "")),
                order=int(getattr(tr, "order", 1) or 1),
                status=_coerce_task_status(getattr(tr, "status", "todo")),
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

    # Final, stable sort of stories by epic priority then story priority, then title
    rank_by_epic = {e.id: (e.priority_rank or 1) for e in epics}
    stories.sort(key=lambda s: (rank_by_epic.get(s.epic_id, 1), s.priority_rank, s.title.lower()))

    return PlanBundle(
        product_vision=ProductVision(**pv.data),
        technical_solution=TechnicalSolution(**ts.data),
        epics=epics,
        stories=stories,
        design_notes=design_notes,
    )
