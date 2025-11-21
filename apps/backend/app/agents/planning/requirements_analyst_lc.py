# apps/backend/app/agents/planning/requirements_analyst_lc.py

from __future__ import annotations
from typing import Any, Dict
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from app.agents.lc.schemas import RAPlanDraft

_SYS = """You are a Requirements Analyst on an Agile Software Delivery team.
Goal: produce **MVP-sized** Epics and Stories that a single coding agent can implement iteratively.

Principles
• Shippable epics: each epic must be a demoable increment (e.g., "App scaffold (baseline)", "Feature X end-to-end").
• No scope creep: use only the items present in *Vision features*. Do not invent features or expand scope.
• Keep it concise: one sentence per description; verb-first titles.
• Avoid proliferation: choose the **fewest** epics/stories that satisfy the Vision.
  Soft caps (ceilings, not targets): ≤{max_epics} epics, ≤{max_stories_total} stories overall, ≤{max_stories_per_epic} per epic.

Behavioral contract for stories
• Each story description must state the intended behavior and an observable outcome, e.g., "Do <X>; Done when <Y is observable>".
• Reference capabilities at the **conceptual layer** (Backend/API, Frontend/UI, Data/Storage, Tests), not concrete files or tools.
• Do **not** prescribe filenames, directories, class/component names, specific libraries, or CLI/tool invocations.
• If Proposed Solution already names interfaces/modules or conventions (e.g., REST vs. RPC, modular boundaries), use those names,
  but keep implementation details conditional on repository conventions to be resolved later by the coding agent.

Output format
• Epics: list of objects with fields: title, description.
• Stories: list of objects with fields: epic_title, title, description.

Rules
• At least one Story per Epic.
• Titles only (no IDs).
• Stories must align to the epic’s increment and be implementation-ready at the behavioral level.
• Respond ONLY with the schema expected by the tool; no extra keys.

CONTEXT:
If provided, incorporate prior feedback to improve the artifact.
--- PRIOR FEEDBACK START ---{feedback_context}--- PRIOR FEEDBACK END ---
"""

_HUMAN = """Context
Vision Features: {features}
Proposed Solution — Modules: {modules}
Proposed Solution — Interfaces: {interfaces}
Proposed Solution — Decisions: {decisions}

Guidance
• Choose epics that map to coherent, shippable increments (scaffold or one end-to-end feature).
• Write stories as concrete behavioral slices expressed in conceptual layers (Backend/API, Frontend/UI, Data/Storage, Tests).
• If the Proposed Solution names interfaces/modules/boundaries, anchor stories to those names; otherwise use generic layer names.
• Maintain bottom-up order within each epic: scaffold → backend slice → UI slice → test/verification.
"""

def make_chain(llm: Any, **knobs: Any) -> Runnable:
    """
    Returns a Runnable mapping {features, modules, interfaces, decisions} -> RAPlanDraft.
    Soft caps are configurable via kwargs: max_epics, max_stories_total, max_stories_per_epic.
    """
    structured_llm = llm.with_structured_output(
        RAPlanDraft,
        method="json_schema",
        strict=True,
    )
    defaults: Dict[str, Any] = {
        "max_epics": 10,
        "max_stories_total": 200,
        "max_stories_per_epic": 20,
    }
    if knobs:
        defaults.update(knobs)
    prompt = ChatPromptTemplate.from_messages([
        ("system", _SYS),
        ("human", _HUMAN),
    ]).partial(**defaults)
    return prompt | structured_llm
