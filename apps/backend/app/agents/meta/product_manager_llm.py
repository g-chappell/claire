from __future__ import annotations
import hashlib
from typing import Dict, List
from types import SimpleNamespace

from app.agents.lc.model_factory import make_chat_model
from app.agents.planning import vision_lc as VISION
from app.agents.planning import architect_lc as ARCH
from app.agents.planning import requirements_analyst_lc as RA
from app.agents.planning import qa_planner_lc as QA
from app.agents.planning import tech_writer_lc as TW

from langchain_core.runnables import RunnableConfig

from app.core.models import (
    ProductVision, TechnicalSolution, Epic, Story, AcceptanceCriteria, PlanBundle, DesignNote, Task
)

RETRY_ATTEMPTS = 2

def _try_invoke(chain, inp):
    err = None
    for _ in range(RETRY_ATTEMPTS):
        try:
            return chain.invoke(inp)
        except Exception as e:
            err = e
            # tighten: add a small “repair” hint to the input for the model
            if isinstance(inp, dict):
                inp = {**inp, "repair_hint": f"Previous output failed schema: {type(e).__name__}. Ensure valid JSON per schema."}
    if err:
        raise err

REQUIRED_STACK = {"node", "vite", "react", "sqlite"}

def _synthesize_tasks_for_story(story: Story, solution: TechnicalSolution) -> list[str]:
    title = (story.title or "").lower()
    desc  = (story.description or "").lower()
    has_endpoint = "endpoint" in title or "/health" in title or "/health" in desc
    items = []

    if has_endpoint:
        items = [
            "Scaffold Express app and router",
            "Add GET /health controller",
            "Wire HealthService.getHealthStatus()",
            "Implement HealthRepository.checkDatabaseConnection()",
            "Return {status:'ok'} with 200 on success; 503 on failure",
            "Register route in server and add OpenAPI doc",
            "Add Jest tests for controller and service",
        ]
    elif "repository" in title:
        items = [
            "Create HealthRepository module",
            "Implement checkDatabaseConnection() using sqlite client",
            "Add error handling and timeouts",
            "Export repository factory for DI",
            "Write Jest unit tests with connection mock",
        ]
    elif "service" in title:
        items = [
            "Create HealthService module",
            "Implement getHealthStatus() aggregating repository result",
            "Map status to {UP/DOWN} JSON",
            "Handle exceptions from repository",
            "Write Jest unit tests for happy/error paths",
        ]
    elif "frontend" in title or "component" in title:
        items = [
            "Create HealthComponent in React",
            "Create ApiClient.fetchHealthStatus()",
            "Render status with loading and error states",
            "Add basic styles and accessibility",
            "Write component tests (React Testing Library)",
        ]
    else:
        items = [
            "Define detailed requirements",
            "Implement core logic",
            "Add error handling and logging",
            "Write unit tests and docs",
        ]
    return items[:8]

def _normalize_stack(stack_items):
    norm_map = {
        "node.js":"node","nodejs":"node","node js":"node",
        "reactjs":"react","sqlite3":"sqlite",
        "express.js":"express"
        }
    out = set()
    for s in (stack_items or []):
        k = str(s).strip().lower()
        for sep in (" - ", "—", ":", "|", "("):
            if sep in k:
                k = k.split(sep, 1)[0].strip()
                break
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
        self.tw_notes_chain = TW.make_notes_chain(self.llm)
        self.tw_tasks_chain = TW.make_tasks_chain(self.llm)

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
            epic_id = epics[0].id if epics else _gen_id("E", requirement["id"] + ":default")
        if not epics:
            epics.append(Epic(id=epic_id, title="Default Epic", description="", priority_rank=1))
            sid = _gen_id("S", requirement["id"] + ":" + sd.title)
            stories.append(Story(
                id=sid, epic_id=epic_id, title=sd.title, description=sd.description,
                priority_rank=1, acceptance=[], tests=[]
            ))
        
        if not stories:
            # synthesize one story per epic to keep plan usable
            for e in epics:
                sid = _gen_id("S", requirement["id"] + ":" + e.title)
                stories.append(Story(
                    id=sid,
                    epic_id=e.id,
                    title=f"Deliver {e.title}",
                    description=e.description or "",
                    priority_rank=1,
                    acceptance=[],
                    tests=[],
                ))

        # 4) PM ordering (deterministic ranks)
        epics, stories = _order_epics_and_stories(epics, stories)

        # --- Tech Writer: Design Notes ---
        notes_bundle = _try_invoke(self.tw_notes_chain, {
            "features": ", ".join(vision.features),
            "stack": ", ".join(solution.stack),
            "modules": ", ".join(solution.modules),
            "interfaces": ", ".join(f"{k}:{v}" for k,v in (solution.interfaces or {}).items()),
            "decisions": ", ".join(solution.decisions or []),
            "epic_titles": ", ".join(e.title for e in epics[:6]),
            "story_titles": ", ".join(s.title for s in stories[:12]),
        })
        notes = getattr(notes_bundle, "notes", []) or []

        # --- Tech Writer: Tasks per story (map over stories) ---
        task_inputs = []
        epic_title_by_id = {e.id: e.title for e in epics}
        for s in stories:
            gherkin_list = [ac.gherkin for ac in (s.acceptance or []) if ac.gherkin]
            task_inputs.append({
                "story_title": s.title,
                "story_description": s.description,
                "epic_title": epic_title_by_id.get(s.epic_id, ""),
                "interfaces": ", ".join(f"{k}:{v}" for k, v in (solution.interfaces or {}).items()),
                "gherkin": "\n".join(gherkin_list) if gherkin_list else "",
            })

        # A strict batch with second-chance retry per item
        task_drafts = []
        for inp in task_inputs:
            task_drafts.append(_try_invoke(self.tw_tasks_chain, inp))

        # Map titles -> ids
        epic_id_by_title = {e.title.strip().lower(): e.id for e in epics}
        story_id_by_title = {s.title.strip().lower(): s.id for s in stories}

        # Build DesignNotes
        design_notes: list[DesignNote] = []
        for nd in notes:
            dn_id = _gen_id("DN", requirement["id"] + ":" + nd.title)
            design_notes.append(DesignNote(
                id=dn_id,
                title=nd.title,
                kind=nd.kind,
                body_md=nd.body_md,
                tags=getattr(nd, "tags", []),
                related_epic_ids=[epic_id_by_title.get(t.strip().lower()) for t in getattr(nd,"related_epic_titles",[]) if epic_id_by_title.get(t.strip().lower())],
                related_story_ids=[story_id_by_title.get(t.strip().lower()) for t in getattr(nd,"related_story_titles",[]) if story_id_by_title.get(t.strip().lower())],
            ))

        # Build Tasks (STRICT: from LLM only; no defaults)
        tasks_by_story: dict[str, list[Task]] = {s.id: [] for s in stories}
        for td in task_drafts:
            title_key = getattr(td, "story_title", "").strip().lower()
            sid = story_id_by_title.get(title_key)
            if not sid:
                continue
            for i, title in enumerate(td.items or [], start=1):
                tid = _gen_id("T", requirement["id"] + ":" + sid + f":{i}:{title}")
                tasks_by_story[sid].append(Task(id=tid, story_id=sid, title=title, order=i, status="todo"))

        for s in stories:
            s.tasks = tasks_by_story.get(s.id, [])

        # 5) QA per story (batch)
        inputs = [{
            "title": s.title,
            "description": s.description,
            "epic_title": next((e.title for e in epics if e.id == s.epic_id), ""),
            "interfaces": ", ".join(f"{k}:{v}" for k, v in (solution.interfaces or {}).items()),
        } for s in stories]
       
        try:
            qa_results = self.qa_chain.batch(inputs, max_concurrency=4) or [None] * len(stories)
        except Exception as e:
            # Never fail planning because QA parsing failed
            solution.decisions = (solution.decisions or []) + [f"QA parse failed ({type(e).__name__}); continuing."]
            qa_results = [None] * len(stories)

        # attach AC/tests
        for s, qa in zip(stories, qa_results):
            gherkins = getattr(qa, "gherkin", None) or [
                "Given the system is running\nWhen the user performs the main action\nThen an observable successful result is returned"
            ]
            s.acceptance = [AcceptanceCriteria(story_id=s.id, gherkin=g) for g in gherkins]
            s.tests = getattr(qa, "unit_tests", None) or ["unit tests cover happy path and validation"]

        return PlanBundle(
            product_vision=vision,
            technical_solution=solution,
            epics=epics,
            stories=stories,
            design_notes=design_notes,
        )
