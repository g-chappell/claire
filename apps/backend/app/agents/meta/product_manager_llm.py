from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional, Sequence, Tuple, Type, TypeVar, cast

from pydantic import BaseModel

from langchain_core.runnables import RunnableConfig

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

# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------

T = TypeVar("T", bound=BaseModel)

RETRY_ATTEMPTS = 2
REQUIRED_STACK = {"node", "vite", "react", "sqlite"}


def _gen_id(prefix: str, raw: str) -> str:
    return f"{prefix}_{hashlib.md5(raw.encode('utf-8')).hexdigest()[:10]}"


def _try_invoke(chain, inp: Dict[str, Any]):
    """
    Invoke a LangChain chain with a simple second-chance retry that hints schema repair.
    """
    err: Optional[Exception] = None
    payload: Dict[str, Any] = dict(inp)
    for _ in range(RETRY_ATTEMPTS):
        try:
            return chain.invoke(payload)
        except Exception as e:  # parsing/validation hiccup
            err = e
            payload = {
                **payload,
                "repair_hint": f"Previous output failed schema: {type(e).__name__}. "
                "Return VALID JSON for the requested schema (no extra keys).",
            }
    if err:
        raise err


def _invoke_typed(expected_type: Type[T], chain, inp: Dict[str, Any]) -> T:
    """
    Invoke the chain and normalize the result into the expected Pydantic model type.
    This both satisfies Pylance and hardens runtime parsing.
    """
    out: Any = _try_invoke(chain, inp)

    # If the chain already returned a BaseModel, normalize to dict first
    if isinstance(out, BaseModel):
        return expected_type.model_validate(obj=out.model_dump())

    # If it returned a dict (common), validate into the model
    if isinstance(out, dict):
        return expected_type.model_validate(obj=out)

    # Fallback: let Pylance know we return T while avoiding runtime breakage
    # (You can raise instead if you want strictness.)
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
        # Bind role chains
        self.vision_chain = VISION.make_chain(llm)
        self.arch_chain = ARCH.make_chain(llm)
        self.ra_chain = RA.make_chain(llm)
        self.qa_chain = QA.make_chain(llm)
        self.tw_notes_chain = TW.make_notes_chain(llm)
        self.tw_tasks_chain = TW.make_tasks_chain(llm)

    # ---------- Stage A: generate vision + solution (the "gate") ----------

    def plan_vision_solution(
        self,
        requirement: Dict[str, str],
        config: Optional[RunnableConfig] = None,
    ) -> Tuple[ProductVision, TechnicalSolution]:
        """
        Generate ProductVision and TechnicalSolution only. Use this to implement the 'gate' UX.
        """
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
            },
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
            },
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
        config: Optional[RunnableConfig] = None,
    ) -> PlanBundle:
        """
        Given an approved ProductVision + TechnicalSolution, produce the rest of the bundle.
        """
        # Requirements Analyst → Epics + Stories
        ra_draft: RAPlanDraft = _invoke_typed(
            RAPlanDraft,
            self.ra_chain,
            {
                "features": ", ".join(vision.features),
                "modules": ", ".join(solution.modules),
                "interfaces": ", ".join(f"{k}:{v}" for k, v in (solution.interfaces or {}).items()),
                "decisions": ", ".join(solution.decisions or []),
            },
        )

        # Map epics
        epic_map: Dict[str, str] = {}  # epic_title -> epic_id
        epics: List[Epic] = []
        for ed in ra_draft.epics or []:
            eid = _gen_id("E", requirement.get("id", "") + ":" + ed.title)
            epic_map[ed.title.strip().lower()] = eid
            epics.append(Epic(id=eid, title=ed.title, description=ed.description or "", priority_rank=1))

        # Map stories to epic_ids (by epic_title)
        stories: List[Story] = []
        for sd in ra_draft.stories or []:
            epic_id = epic_map.get((sd.epic_title or "").strip().lower())
            if not epic_id:
                epic_id = epics[0].id if epics else _gen_id("E", requirement.get("id", "") + ":default")
                if not epics:
                    epics.append(Epic(id=epic_id, title="Default Epic", description="", priority_rank=1))
            sid = _gen_id("S", requirement.get("id", "") + ":" + sd.title)
            stories.append(
                Story(
                    id=sid,
                    epic_id=epic_id,
                    title=sd.title,
                    description=sd.description or "",
                    priority_rank=1,
                    acceptance=[],
                    tests=[],
                )
            )

        # If the model somehow emitted nothing, keep the plan usable
        if not stories:
            if not epics:
                epic_id = _gen_id("E", requirement.get("id", "") + ":default")
                epics.append(Epic(id=epic_id, title="Default Epic", description="", priority_rank=1))
            for e in epics:
                sid = _gen_id("S", requirement.get("id", "") + ":" + e.title)
                stories.append(
                    Story(
                        id=sid,
                        epic_id=e.id,
                        title=f"Deliver {e.title}",
                        description=e.description or "",
                        priority_rank=1,
                        acceptance=[],
                        tests=[],
                    )
                )

        # PM ordering
        epics, stories = _order_epics_and_stories(epics, stories)

        # ---------- QA per story (so we can feed AC into tasks) ----------
        qa_inputs = [
            {
                "title": s.title,
                "description": s.description,
                "epic_title": next((e.title for e in epics if e.id == s.epic_id), ""),
                "interfaces": ", ".join(f"{k}:{v}" for k, v in (solution.interfaces or {}).items()),
            }
            for s in stories
        ]
        try:
            qa_results_any = self.qa_chain.batch(qa_inputs, max_concurrency=4) or [None] * len(stories)
            qa_results: List[Optional[QASpec]] = cast(List[Optional[QASpec]], qa_results_any)
        except Exception as e:
            # Never fail planning because QA parse failed
            solution.decisions = (solution.decisions or []) + [f"QA parse failed ({type(e).__name__}); continuing."]
            qa_results = [None] * len(stories)

        for s, qa in zip(stories, qa_results):
            gherkins = _sequence_to_list(getattr(qa, "gherkin", None)) if qa else []
            if not gherkins:
                gherkins = [
                    "Given the system is running\nWhen the user performs the main action\nThen an observable successful result is returned"
                ]
            s.acceptance = [AcceptanceCriteria(story_id=s.id, gherkin=g) for g in gherkins]
            s.tests = _sequence_to_list(getattr(qa, "unit_tests", None)) if qa else []

        # ---------- Tech Writer: Design Notes ----------
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
            },
        )
        notes = _sequence_to_list([])  # type: ignore[assignment]
        # notes is a list of DesignNoteDrafts; keep as Any and read attributes defensively
        notes_any: Any = getattr(notes_bundle, "notes", []) or []
        epic_id_by_title = {e.title.strip().lower(): e.id for e in epics}
        story_id_by_title = {s.title.strip().lower(): s.id for s in stories}

        design_notes: List[DesignNote] = []
        for nd in notes_any:
            # Collect related ids, stripping Nones to keep Pylance happy
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

        # ---------- Tech Writer: Tasks per story (batch over stories) ----------
        epic_title_by_id = {e.id: e.title for e in epics}
        task_inputs = []
        for s in stories:
            gherkin_block = "\n".join([ac.gherkin for ac in (s.acceptance or []) if ac.gherkin])
            task_inputs.append(
                {
                    "story_title": s.title,
                    "story_description": s.description,
                    "epic_title": epic_title_by_id.get(s.epic_id, ""),
                    "interfaces": ", ".join(f"{k}:{v}" for k, v in (solution.interfaces or {}).items()),
                    "gherkin": gherkin_block,
                }
            )

        task_drafts_any = [ _try_invoke(self.tw_tasks_chain, inp) for inp in task_inputs ]
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
                tasks_by_story[sid].append(Task(id=tid, story_id=sid, title=title, order=i, status="todo"))

        for s in stories:
            s.tasks = tasks_by_story.get(s.id, [])

        return PlanBundle(
            product_vision=vision,
            technical_solution=solution,
            epics=epics,
            stories=stories,
            design_notes=design_notes,
        )

    # ---------- Convenience: full single-shot plan (kept for parity) ----------

    def plan(self, requirement: Dict[str, str], config: Optional[RunnableConfig] = None) -> PlanBundle:
        """
        Backwards-compatible single call that does both stages.
        """
        vision, solution = self.plan_vision_solution(requirement, config=config)
        return self.plan_remaining(requirement, vision, solution, config=config)
