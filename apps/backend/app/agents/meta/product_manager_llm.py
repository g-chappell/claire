from __future__ import annotations
import hashlib
from typing import Dict, List

from langchain_core.runnables import RunnableParallel

from app.agents.lc.model_factory import make_chat_model
from app.agents.planning import vision_lc as VISION
from app.agents.planning import architect_lc as ARCH
from app.agents.planning import requirements_analyst_lc as RA
from app.agents.planning import qa_planner_lc as QA

from app.core.models import (
    ProductVision, TechnicalSolution, Epic, Story, AcceptanceCriteria, PlanBundle
)

REQUIRED_STACK = {"node", "vite", "react", "sqlite"}

def _normalize_stack(stack_items):
    norm_map = {"node.js": "node", "nodejs": "node", "node js": "node",
                "reactjs": "react", "sqlite3": "sqlite"}
    out = set()
    for s in (stack_items or []):
        k = str(s).strip().lower()
        out.add(norm_map.get(k, k))
    return out

def _gen_id(prefix: str, seed: str) -> str:
    h = hashlib.sha1(seed.encode()).hexdigest()[:8]
    return f"{prefix}-{h}"

def _order_epics_and_stories(epics: List[Epic], stories: List[Story]) -> tuple[List[Epic], List[Story]]:
    # Deterministic: preserve generation order; assign priority_rank = index+1 within each set
    for i, e in enumerate(epics, start=1):
        epics[i-1] = Epic(**{**e.model_dump(), "priority_rank": i})
    # stories ordered within each epic
    by_epic: Dict[str, List[Story]] = {}
    for s in stories:
        by_epic.setdefault(s.epic_id, []).append(s)
    new_stories: List[Story] = []
    for e in epics:
        group = by_epic.get(e.id, [])
        for j, s in enumerate(group, start=1):
            new_stories.append(Story(**{**s.model_dump(), "priority_rank": j}))
    return epics, new_stories

def _validate_guardrails(ts: TechnicalSolution):
    stack = {x.lower() for x in (ts.stack or [])}
    missing = REQUIRED_STACK - stack
    if missing:
        raise ValueError(f"Solution violates guardrails; missing stack items: {sorted(missing)}")

def _guardrail_warnings(ts: TechnicalSolution) -> list[str]:
    stack = _normalize_stack(ts.stack)
    missing = sorted(REQUIRED_STACK - stack)
    if missing:
        return [f"Guardrail: expected stack to include {sorted(REQUIRED_STACK)}; missing {missing}"]
    return []

class ProductManagerLLM:
    def __init__(self):
        self.llm = make_chat_model()
        self.vision_chain = VISION.make_chain(self.llm)
        self.arch_chain   = ARCH.make_chain(self.llm)
        self.ra_chain     = RA.make_chain(self.llm)
        self.qa_chain     = QA.make_chain(self.llm)

    def plan(self, requirement: Dict) -> PlanBundle:
        # 1) Vision
        v = self.vision_chain.invoke({
            "req_id": requirement["id"],
            "title": requirement["title"],
            "description": requirement["description"],
            "constraints": ", ".join(requirement.get("constraints") or []),
            "nfr": ", ".join(requirement.get("non_functionals") or []),
        })
        vision = ProductVision(
            id=_gen_id("PV", requirement["id"]),
            goals=v.goals, personas=v.personas, features=v.features
        )

        # 2) Solution (guardrails enforced)
        sol_draft = self.arch_chain.invoke({
            "title": requirement["title"],
            "features": ", ".join(vision.features),
            "constraints": ", ".join(requirement.get("constraints") or []),
            "nfr": ", ".join(requirement.get("non_functionals") or []),
        })
        solution = TechnicalSolution(
            id=_gen_id("TS", requirement["id"]),
            stack=sol_draft.stack, modules=sol_draft.modules,
            interfaces=sol_draft.interfaces, decisions=sol_draft.decisions
        )
        warnings = _guardrail_warnings(solution)
        if warnings:
            # record as decisions so it surfaces but does not block
            solution.decisions = (solution.decisions or []) + warnings

        # 3) Requirements Analyst → epics+stories (drafts) then assign IDs
        ra = self.ra_chain.invoke({
            "features": ", ".join(vision.features),
            "modules": ", ".join(solution.modules),
            "interfaces": ", ".join(f"{k}:{v}" for k, v in (solution.interfaces or {}).items()),
            "decisions": ", ".join(solution.decisions),
        })
        # map epics
        epic_map: Dict[str, str] = {}  # epic_title -> epic_id
        epics: List[Epic] = []
        for ed in ra.epics:
            eid = _gen_id("E", requirement["id"] + ":" + ed.title)
            epic_map[ed.title.strip().lower()] = eid
            epics.append(Epic(id=eid, title=ed.title, description=ed.description, priority_rank=1))
        # map stories to epic_ids (by epic_title)
        stories: List[Story] = []
        for sd in ra.stories:
            epic_id = epic_map.get(sd.epic_title.strip().lower())
            if not epic_id:
                # fallback: if missing, attach to first epic
                epic_id = epics[0].id if epics else _gen_id("E", requirement["id"] + ":default")
                if not epics:
                    epics.append(Epic(id=epic_id, title="Default Epic", description="", priority_rank=1))
            sid = _gen_id("S", requirement["id"] + ":" + sd.title)
            stories.append(Story(
                id=sid, epic_id=epic_id, title=sd.title, description=sd.description,
                priority_rank=1, acceptance=[], tests=[]
            ))

        # 4) PM ordering (deterministic ranks)
        epics, stories = _order_epics_and_stories(epics, stories)

        # 5) QA per story (batch)
        inputs = [{
            "title": s.title,
            "description": s.description,
            "epic_title": next((e.title for e in epics if e.id == s.epic_id), ""),
            "interfaces": ", ".join(f"{k}:{v}" for k, v in (solution.interfaces or {}).items()),
        } for s in stories]
        qa_results = self.qa_chain.batch(inputs, max_concurrency=4)

        # attach AC/tests
        for s, qa in zip(stories, qa_results):
            gherkins = qa.gherkin or [
                "Given the system is running\nWhen the user performs the main action\nThen an observable successful result is returned"
            ]
            s.acceptance = [AcceptanceCriteria(story_id=s.id, gherkin=g) for g in gherkins]
            s.tests = qa.unit_tests or ["unit tests cover happy path and validation"]

        return PlanBundle(
            product_vision=vision,
            technical_solution=solution,
            epics=epics,
            stories=stories,
        )
