# apps/backend/agents/meta/product_manager_llm.py
from __future__ import annotations

from sqlalchemy.orm import Session

from app.storage.models import (
    ProductVisionORM, TechnicalSolutionORM,
    EpicORM, StoryORM, TaskORM
)

import hashlib
from typing import Any, Dict, List, Optional, Sequence, Tuple, Type, TypeVar, cast

from pydantic import BaseModel

# RunnableConfig import path is stable in v1, but keep a small fallback for envs that differ
try:
    from langchain_core.runnables import RunnableConfig
except Exception:  # pragma: no cover
    from langchain_core.runnables.config import RunnableConfig  # type: ignore

from app.agents.lc.model_factory import make_chat_model
from app.agents.planning import vision_lc as VISION
from app.agents.planning import architect_lc as ARCH
from app.agents.planning import requirements_analyst_lc as RA
from app.agents.planning import qa_planner_lc as QA
from app.agents.planning import tech_writer_lc as TW
from app.agents.lc.schemas import (
    ProductVisionDraft,
    TechnicalSolutionDraft,
    RAPlanDraft,
    QASpec,
    TechWritingBundleDraft,
    TaskDraft,
)

from app.core.models import (
    AcceptanceCriteria,
    DesignNote,
    Epic,
    PlanBundle,
    ProductVision,
    Story,
    Task,
    TechnicalSolution,
)

import random
import time
import logging

try:
    from anthropic._exceptions import (
        OverloadedError,
        RateLimitError,
        APITimeoutError,
        APIStatusError,
    )
    PROVIDER_EXCEPTIONS = (OverloadedError, RateLimitError, APITimeoutError, APIStatusError)
except Exception:
    PROVIDER_EXCEPTIONS = tuple()

PROVIDER_TRANSIENT_STATUSES = {429, 500, 502, 503, 504, 529}

from app.configs.settings import get_settings
settings = get_settings()
logger = logging.getLogger(__name__)



# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------

T = TypeVar("T", bound=BaseModel)

RETRY_ATTEMPTS = 2
REQUIRED_STACK = {"node", "vite", "react", "sqlite"}


def _gen_id(prefix: str, raw: str) -> str:
    return f"{prefix}_{hashlib.md5(raw.encode('utf-8')).hexdigest()[:10]}"


def _try_invoke(
    chain,
    inp: Dict[str, Any],
    config: Optional[RunnableConfig] = None,
    max_attempts: int = 6,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
):
    """
    Resilient invoke with exponential backoff + jitter for transient provider issues.
    Also attempts one schema-repair retry by injecting a 'repair_hint' if a non-transient error occurs.
    """
    payload: Dict[str, Any] = dict(inp)
    tried_repair = False

    for attempt in range(1, max_attempts + 1):
        try:
            return chain.invoke(payload, config=config)

        except Exception as e:
            # Treat Anthropic overload/rate limit/timeouts (if available) or HTTP-style transient statuses as retryable.
            status = getattr(e, "status_code", None)
            is_provider_exc = isinstance(e, PROVIDER_EXCEPTIONS)
            transient = is_provider_exc or (status in PROVIDER_TRANSIENT_STATUSES)

            if transient and attempt < max_attempts:
                # Exponential backoff with jitter (0.6x–1.4x)
                delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
                delay *= (0.6 + random.random() * 0.8)
                time.sleep(delay)
                continue

            # If it's not transient, attempt one schema-repair pass
            if not transient and not tried_repair:
                tried_repair = True
                payload = {
                    **payload,
                    "repair_hint": (
                        f"Previous output failed schema: {type(e).__name__}. "
                        "Return VALID JSON for the requested schema (no extra keys)."
                    ),
                }
                time.sleep(0.4)
                continue

            # Give up
            raise


def _invoke_typed(expected_type: Type[T], chain, inp: Dict[str, Any], config: Optional[RunnableConfig] = None) -> T:
    """
    Invoke the chain and normalize the result into the expected Pydantic model type.
    This both satisfies type checkers and hardens runtime parsing.
    """
    out: Any = _try_invoke(chain, inp, config=config)

    # If the chain already returned a BaseModel, normalize to dict first
    if isinstance(out, BaseModel):
        return expected_type.model_validate(obj=out.model_dump())

    # If it returned a dict (common), validate into the model
    if isinstance(out, dict):
        return expected_type.model_validate(obj=out)

    # Fallback: let the type system know we return T while avoiding runtime breakage
    # (Alternatively, raise a ValueError here if you require strictness.)
    return cast(T, out)


def _sequence_to_list(xs: Optional[Sequence[str]]) -> List[str]:
    return [x for x in (xs or []) if isinstance(x, str) and x.strip()]


def _normalize_stack(items: Sequence[str]) -> set[str]:
    norm = set()
    for it in items:
        it = (it or "").lower()
        # split common composite tokens
        for tok in it.replace("+", " ").replace("/", " ").replace(",", " ").split():
            tok = tok.strip()
            if tok:
                norm.add(tok)
    return norm


def _order_epics_and_stories(epics: List[Epic], stories: List[Story]) -> Tuple[List[Epic], List[Story]]:
    """
    Deterministic but human-ish ordering: by hashed title; stories grouped under epics.
    """
    epics_sorted = sorted(epics, key=lambda e: hashlib.md5((e.title or "").encode()).hexdigest())
    rank_by_epic = {e.id: i + 1 for i, e in enumerate(epics_sorted)}
    for e in epics_sorted:
        e.priority_rank = rank_by_epic[e.id]

    stories_sorted = sorted(
        stories,
        key=lambda s: (rank_by_epic.get(s.epic_id, 9999), hashlib.md5((s.title or "").encode()).hexdigest()),
    )
    for i, s in enumerate(stories_sorted, start=1):
        s.priority_rank = i
    return epics_sorted, stories_sorted


def _guardrail_warnings(sol: TechnicalSolution) -> List[str]:
    """
    Ensure minimal stack is present; emit guardrail notes into decisions if needed.
    """
    warnings: List[str] = []
    stack = _normalize_stack(sol.stack or [])
    missing = [x for x in REQUIRED_STACK if x not in stack]
    if missing:
        warnings.append(f"Missing required stack items: {', '.join(sorted(missing))}.")
    return warnings

def build_feedback_context_for_run(
    db: Session,
    run_id: str,
    epic_title: Optional[str] = None,
    story_title: Optional[str] = None,
) -> str:
    """
    Minimal, local-only context for *this run*.
    Later, swap to RAG to pull 'similar runs'.
    """
    chunks: list[str] = []

    pv = db.query(ProductVisionORM).filter_by(run_id=run_id).first()
    if pv:
        fh = (pv.data or {}).get("feedback_human")
        fa = (pv.data or {}).get("feedback_ai")
        if fh or fa:
            chunks.append(f"Product Vision feedback:\n- Human: {fh or ''}\n- AI: {fa or ''}")

    ts = db.query(TechnicalSolutionORM).filter_by(run_id=run_id).first()
    if ts:
        fh = (ts.data or {}).get("feedback_human")
        fa = (ts.data or {}).get("feedback_ai")
        if fh or fa:
            chunks.append(f"Technical Solution feedback:\n- Human: {fh or ''}\n- AI: {fa or ''}")

    # Epic / Story scoping (same-run only)
    if epic_title:
        epic = db.query(EpicORM).filter_by(run_id=run_id, title=epic_title).first()
        if epic and (epic.feedback_human or epic.feedback_ai):
            chunks.append(f"Epic '{epic.title}' feedback:\n- Human: {epic.feedback_human or ''}\n- AI: {epic.feedback_ai or ''}")

    if story_title:
        story = db.query(StoryORM).filter_by(run_id=run_id, title=story_title).first()
        if story:
            if story.feedback_human or story.feedback_ai:
                chunks.append(f"Story '{story.title}' feedback:\n- Human: {story.feedback_human or ''}\n- AI: {story.feedback_ai or ''}")
            # also include any task-level feedback for this story
            task_rows = db.query(TaskORM).filter_by(run_id=run_id, story_id=story.id).all()
            for t in task_rows:
                if t.feedback_human or t.feedback_ai:
                    chunks.append(f"Task '{t.title}' feedback:\n- Human: {t.feedback_human or ''}\n- AI: {t.feedback_ai or ''}")

    # conservative cap
    text = "\n\n".join(chunks)
    return text[:4000]

# --------------------------------------------------------------------------------------
# Orchestrator
# --------------------------------------------------------------------------------------

class ProductManagerLLM:
    """
    Orchestrates the planning workflow by calling role chains (vision, architect, RA, QA, tech-writer).
    Note: This 'meta agent' is a coordinator; the only 'agents' here are the role chains.
    """

    def __init__(self, model: Optional[str] = None):
        llm = make_chat_model(model)
        logger.info(
            "PM_INIT provider=%s model=%s",
            getattr(settings, "LLM_PROVIDER", "unknown"),
            model or getattr(settings, "LLM_MODEL", "unknown"),
        )
        self.vision_chain = VISION.make_chain(llm)
        self.arch_chain = ARCH.make_chain(llm)
        # RA chains:
        # - ra_chain          : full / best context engineering (structured + features_only)
        # - ra_chain_minimal  : basic context engineering (minimal mode)
        self.ra_chain = RA.make_chain(llm)
        self.ra_chain_minimal = RA.make_minimal_chain(llm)
        self.qa_chain = QA.make_chain(llm) if settings.FEATURE_QA else None
        self.tw_notes_chain = TW.make_notes_chain(llm) if settings.FEATURE_DESIGN_NOTES else None
        self.tw_tasks_chain = TW.make_tasks_chain(llm)

    # ---------- Stage A: generate vision + solution (the "gate") ----------

    def plan_vision_solution(
        self,
        requirement: Dict[str, str],
        db: Session, run_id: str,
        config: Optional[RunnableConfig] = None,
    ) -> Tuple[ProductVision, TechnicalSolution]:
        """
        Generate ProductVision and TechnicalSolution only. Use this to implement the 'gate' UX.
        """
        fctx = build_feedback_context_for_run(db, run_id=run_id)

        # Vision
        v_draft: ProductVisionDraft = _invoke_typed(
            ProductVisionDraft,
            self.vision_chain,
            {
                "req_id": requirement.get("id", ""),
                "title": requirement.get("title", ""),
                "description": requirement.get("description", ""),
                "constraints": requirement.get("constraints", ""),
                "nfr": requirement.get("nfr", ""),
                "feedback_context": fctx,
            },
            config=config,
        )
        vision = ProductVision(
            id=_gen_id("PV", requirement.get("id", "")),
            personas=_sequence_to_list(getattr(v_draft, "personas", None)),
            features=_sequence_to_list(getattr(v_draft, "features", None)),
            goals=_sequence_to_list(getattr(v_draft, "goals", None)),
        )

        # Architecture
        a_draft: TechnicalSolutionDraft = _invoke_typed(
            TechnicalSolutionDraft,
            self.arch_chain,
            {
                "title": requirement.get("title", ""),
                "features": ", ".join(vision.features),
                "constraints": requirement.get("constraints", ""),
                "nfr": requirement.get("nfr", ""),
                "feedback_context": fctx,
            },
            config=config,
        )
        solution = TechnicalSolution(
            id=_gen_id("TS", requirement.get("id", "")),
            stack=_sequence_to_list(a_draft.stack),
            modules=_sequence_to_list(a_draft.modules),
            interfaces=dict(a_draft.interfaces or {}),
            decisions=_sequence_to_list(a_draft.decisions),
        )

        # Guardrail notes (persist as decisions)
        warn = _guardrail_warnings(solution)
        if warn:
            solution.decisions = (solution.decisions or []) + [f"PM guardrail: {w}" for w in warn]

        return vision, solution

    # ---------- Stage B: continue to epics/stories/notes/tasks + QA ----------

    def plan_remaining(
        self,
        requirement: Dict[str, str],
        vision: ProductVision,
        solution: TechnicalSolution,
        db: Session,
        run_id: str,
        prompt_context_mode: str = "structured",
        config: Optional[RunnableConfig] = None,
    ) -> PlanBundle:
        """
        Given an approved ProductVision + TechnicalSolution, produce the rest of the bundle.
        """

        # Global feedback context for this run (used by most sub-chains)
        fctx_global = build_feedback_context_for_run(db, run_id=run_id)

        # Requirements Analyst → Epics + Stories
        # Experiment knob (per-run): prompt_context_mode
        # - "structured":    full TS context + best RA prompt
        # - "features_only": features-only ablation (no TS/feedback context, best RA prompt)
        # - "minimal":       features-only + basic RA prompt (weakest context engineering)
        mode = (prompt_context_mode or "structured").strip().lower()
        # Back-compat: treat any legacy "flat" value as "features_only"
        if mode == "flat":
            mode = "features_only"
        if mode not in {"structured", "features_only", "minimal"}:
            mode = "structured"

        logger.info(
            "PM_RA_CONTEXT run=%s mode=%s features=%d modules=%d decisions=%d has_feedback=%s",
            run_id,
            mode,
            len(vision.features or []),
            len(solution.modules or []),
            len(solution.decisions or []),
            bool(fctx_global),
        )

        if mode == "structured":
            # Full TS + feedback context (best context engineering)
            ra_inputs = {
                "features": ", ".join(vision.features),
                "modules": ", ".join(solution.modules),
                "interfaces": ", ".join(
                    f"{k}:{v}" for k, v in (solution.interfaces or {}).items()
                ),
                "decisions": ", ".join(solution.decisions or []),
                "feedback_context": fctx_global,
            }
        else:
            # features_only / minimal → ablate TS + feedback context
            ra_inputs = {
                "features": ", ".join(vision.features),
                # strip architecture + decisions + feedback context for ablation
                "modules": "",
                "interfaces": "",
                "decisions": "",
                "feedback_context": "",
            }

        # Choose RA chain based on mode
        if mode == "minimal":
            ra_chain = self.ra_chain_minimal
        else:
            # structured + features_only both use the full/best RA prompt
            ra_chain = self.ra_chain

        ra_draft: RAPlanDraft = _invoke_typed(
            RAPlanDraft,
            ra_chain,
            ra_inputs,
            config=config,
        )

        logger.info(
            "PM_RA_OUTPUT run=%s mode=%s epics=%d stories=%d",
            run_id,
            mode,
            len(ra_draft.epics or []),
            len(ra_draft.stories or []),
        )

        # Map epics from RA plan — preserve LLM priority_ranks and dependencies
        epics: List[Epic] = []
        epic_id_by_title: Dict[str, str] = {}

        for ed in ra_draft.epics or []:
            title = (ed.title or "").strip()
            if not title:
                continue
            eid = _gen_id("E", requirement.get("id", "") + ":" + title)
            epic_id_by_title[title.lower()] = eid
            epics.append(
                Epic(
                    id=eid,
                    title=ed.title,
                    description=ed.description or "",
                    priority_rank=ed.priority_rank or 1,
                    depends_on=[],  # filled after all epics are known
                )
            )

        # Fallback: ensure at least one epic exists
        if not epics:
            default_title = "Default Epic"
            eid = _gen_id("E", requirement.get("id", "") + ":" + default_title)
            epic_id_by_title[default_title.lower()] = eid
            epics.append(
                Epic(
                    id=eid,
                    title=default_title,
                    description="",
                    priority_rank=1,
                    depends_on=[],
                )
            )

        # Wire epic-level dependencies using epic titles from the RA plan
        for ed in ra_draft.epics or []:
            src_title = (ed.title or "").strip()
            if not src_title:
                continue
            src_id = epic_id_by_title.get(src_title.lower())
            if not src_id:
                continue
            epic = next((e for e in epics if e.id == src_id), None)
            if not epic:
                continue
            dep_ids: List[str] = []
            for dep_name in ed.depends_on or []:
                key = (dep_name or "").strip().lower()
                if not key:
                    continue
                dep_id = epic_id_by_title.get(key)
                if dep_id and dep_id != epic.id and dep_id not in dep_ids:
                    dep_ids.append(dep_id)
            epic.depends_on = dep_ids

        # Map stories from RA plan — preserve LLM priority_ranks and dependencies
        stories: List[Story] = []
        story_id_by_title_and_epic: Dict[tuple[str, str], str] = {}

        for sd in ra_draft.stories or []:
            story_title = (sd.title or "").strip()
            epic_title = (sd.epic_title or "").strip()
            if not story_title:
                continue

            epic_id = epic_id_by_title.get(epic_title.lower()) if epic_title else None
            if not epic_id:
                # fall back to the first epic if mapping fails
                epic_id = epics[0].id

            sid = _gen_id("S", requirement.get("id", "") + ":" + story_title)
            story = Story(
                id=sid,
                epic_id=epic_id,
                title=sd.title,
                description=sd.description or "",
                priority_rank=sd.priority_rank or 1,
                acceptance=[],
                tests=[],
                depends_on=[],  # filled after all stories are known
            )
            stories.append(story)
            story_id_by_title_and_epic[(story_title.lower(), epic_id)] = sid

        # If the model somehow emitted no stories, keep the plan usable
        if not stories:
            for e in epics:
                story_title = f"Deliver {e.title}"
                sid = _gen_id("S", requirement.get("id", "") + ":" + story_title)
                story = Story(
                    id=sid,
                    epic_id=e.id,
                    title=story_title,
                    description=e.description or "",
                    priority_rank=1,
                    acceptance=[],
                    tests=[],
                    depends_on=[],
                )
                stories.append(story)
                story_id_by_title_and_epic[(story_title.lower(), e.id)] = sid

        # Wire story-level dependencies using story titles within the same epic
        for sd in ra_draft.stories or []:
            story_title = (sd.title or "").strip()
            epic_title = (sd.epic_title or "").strip()
            if not story_title or not epic_title:
                continue
            epic_id = epic_id_by_title.get(epic_title.lower())
            if not epic_id:
                continue
            sid = story_id_by_title_and_epic.get((story_title.lower(), epic_id))
            if not sid:
                continue
            story = next((s for s in stories if s.id == sid), None)
            if not story:
                continue
            dep_ids: List[str] = []
            for dep_name in sd.depends_on or []:
                key = (dep_name or "").strip().lower()
                if not key:
                    continue
                dep_sid = story_id_by_title_and_epic.get((key, epic_id))
                if dep_sid and dep_sid != story.id and dep_sid not in dep_ids:
                    dep_ids.append(dep_sid)
            story.depends_on = dep_ids

        # Finally, sort epics and stories using the LLM-provided priority ranks
        epics.sort(key=lambda e: e.priority_rank)
        stories.sort(key=lambda s: s.priority_rank)

        # Title->ID maps used by downstream steps (tasks, notes)
        epic_id_by_title: Dict[str, str] = {e.title.strip().lower(): e.id for e in epics}
        story_id_by_title: Dict[str, str] = {s.title.strip().lower(): s.id for s in stories}

        # ---------- QA per story (acceptance/tests) ----------
        if settings.FEATURE_QA and self.qa_chain is not None:
            qa_inputs = []
            for s in stories:
                epic_title = next((e.title for e in epics if e.id == s.epic_id), "")
                fctx_story = build_feedback_context_for_run(
                    db, run_id=run_id, epic_title=epic_title, story_title=s.title
                )
                qa_inputs.append({
                    "title": s.title,
                    "description": s.description,
                    "epic_title": epic_title,
                    "interfaces": ", ".join(f"{k}:{v}" for k, v in (solution.interfaces or {}).items()),
                    "feedback_context": fctx_story,   # <-- story-specific
                })
            try:
                qa_results_any = self.qa_chain.batch(qa_inputs, config=config, max_concurrency=4) or [None] * len(stories)
                qa_results: List[Optional[QASpec]] = cast(List[Optional[QASpec]], qa_results_any)
            except Exception as e:
                solution.decisions = (solution.decisions or []) + [f"QA parse failed ({type(e).__name__}); continuing."]
                qa_results = [None] * len(stories)

            for s, qa in zip(stories, qa_results):
                gherkins = _sequence_to_list(getattr(qa, "gherkin", None)) if qa else []
                s.acceptance = [AcceptanceCriteria(story_id=s.id, gherkin=g) for g in gherkins]
                s.tests = _sequence_to_list(getattr(qa, "unit_tests", None)) if qa else []
        else:
            # QA disabled: ensure stories carry no acceptance/tests
            for s in stories:
                s.acceptance = []
                s.tests = []

        # ---------- Tech Writer: Design Notes ----------
        design_notes: List[DesignNote] = []

        if settings.FEATURE_DESIGN_NOTES and self.tw_notes_chain is not None:
            notes_bundle: TechWritingBundleDraft = _invoke_typed(
                TechWritingBundleDraft,
                self.tw_notes_chain,
                {
                    "features": ", ".join(vision.features),
                    "stack": ", ".join(solution.stack or []),
                    "modules": ", ".join(solution.modules or []),
                    "interfaces": ", ".join(f"{k}:{v}" for k, v in (solution.interfaces or {}).items()),
                    "decisions": ", ".join(solution.decisions or []),
                    "epic_titles": ", ".join(e.title for e in epics[:6]),
                    "story_titles": ", ".join(s.title for s in stories[:12]),
                    "feedback_context": fctx_global,
                },
                config=config,
            )

            notes_any: Any = getattr(notes_bundle, "notes", []) or []

            for nd in notes_any:
                rel_epic_ids = [
                    epic_id_by_title.get(t.strip().lower())
                    for t in _sequence_to_list(getattr(nd, "related_epic_titles", None))
                ]
                rel_story_ids = [
                    story_id_by_title.get(t.strip().lower())
                    for t in _sequence_to_list(getattr(nd, "related_story_titles", None))
                ]
                rel_epic_ids = [x for x in rel_epic_ids if isinstance(x, str)]
                rel_story_ids = [x for x in rel_story_ids if isinstance(x, str)]

                dn_id = _gen_id("DN", requirement.get("id", "") + ":" + getattr(nd, "title", "note"))
                design_notes.append(
                    DesignNote(
                        id=dn_id,
                        title=getattr(nd, "title", ""),
                        kind=getattr(nd, "kind", "other"),
                        body_md=getattr(nd, "body_md", ""),
                        tags=_sequence_to_list(getattr(nd, "tags", None)),
                        related_epic_ids=rel_epic_ids,
                        related_story_ids=rel_story_ids,
                    )
                )
        # else: design_notes remains []

        # ---------- Tech Writer: Tasks per story (batch over stories) ----------
        epic_title_by_id = {e.id: e.title for e in epics}
        task_inputs: List[Dict[str, str]] = []

        for s in stories:
            epic_title = epic_title_by_id.get(s.epic_id, "")
            fctx_story = build_feedback_context_for_run(db, run_id=run_id, epic_title=epic_title, story_title=s.title)
            payload: Dict[str, str] = {
                "story_title": s.title,
                "story_description": s.description,
                "epic_title": epic_title_by_id.get(s.epic_id, ""),
                "interfaces": ", ".join(f"{k}:{v}" for k, v in (solution.interfaces or {}).items()),
                "feedback_context": fctx_story,   # <-- story-specific
            }
            if settings.FEATURE_QA:
                gherkin_block = "\n".join([ac.gherkin for ac in (s.acceptance or []) if getattr(ac, "gherkin", "")])
                payload["gherkin"] = gherkin_block
            task_inputs.append(payload)

        # One call per story, with resilient invoke
        task_drafts_any = [_try_invoke(self.tw_tasks_chain, inp, config=config) for inp in task_inputs]
        task_drafts: List[TaskDraft] = cast(List[TaskDraft], task_drafts_any)

        tasks_by_story: Dict[str, List[Task]] = {s.id: [] for s in stories}
        for td in task_drafts:
            title_key = (getattr(td, "story_title", "") or "").strip().lower()
            sid = story_id_by_title.get(title_key)
            if not sid:
                continue
            items = _sequence_to_list(getattr(td, "items", None))
            for i, title in enumerate(items, start=1):
                tid = _gen_id("T", requirement.get("id", "") + ":" + sid + f":{i}:{title}")
                tasks_by_story[sid].append(
                    Task(id=tid, story_id=sid, title=title, order=i, status="todo")
                )

        for s in stories:
            s.tasks = tasks_by_story.get(s.id, [])
        
        # FINAL RETURN — use the correct PlanBundle field names
        return PlanBundle(
            product_vision=vision,
            technical_solution=solution,
            epics=epics,
            stories=stories,
            design_notes=design_notes,  # [] when FEATURE_DESIGN_NOTES is False
        )
            

    # ---------- Convenience: full single-shot plan (kept for parity) ----------

    def plan(
        self,
        requirement: Dict[str, str],
        db: Session,
        run_id: str,
        prompt_context_mode: str = "structured",
        config: Optional[RunnableConfig] = None,
    ) -> PlanBundle:
        """
        Convenience: run Stage A (PV/TS) then Stage B (epics/stories/etc)
        in one shot, using a per-run prompt_context_mode.
        """
        vision, solution = self.plan_vision_solution(
            requirement,
            db=db,
            run_id=run_id,
            config=config,
        )
        return self.plan_remaining(
            requirement,
            vision,
            solution,
            db=db,
            run_id=run_id,
            prompt_context_mode=prompt_context_mode,
            config=config,
        )
