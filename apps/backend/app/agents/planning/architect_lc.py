#apps/backend/app/agents/planning/architect_lc.py 

from __future__ import annotations
from typing import Any, Dict
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from app.agents.lc.schemas import TechnicalSolutionDraft
 
_SYSTEM = (
    "You are a Solution Architect for Software Development, focused on building lightweight web applications. Propose a **minimal, testable MVP** design for a given requirement."
    "\nStack (fixed, minimum): Node.js, Express.js, React, Zustand, SQLite. Use Vite for tooling."
    "\nScope discipline: implement **only** what appears in *Vision features*; no scope creep."
    "\nInfra discipline: single process, REST over HTTP; avoid microservices, queues, external DBs, background workers, GraphQL, or third-party auth unless explicitly required by *Constraints*."
    "\nIf *Constraints* or *Non-functionals* are blank, proceed with sensible defaults and keep the design simple."
    "\nStyle: concise bullets, **one sentence per bullet**, no marketing language."
    "\nOutput sections:"
    "\n• Stack — exact libraries/tooling (minimal)."
    "\n• Modules — high-level components/services with a brief purpose."
    "\n• Interfaces — for each module, list key functions as name -> signature."
    "\n• Data Model — required tables with essential columns."
    "\n• Key Decisions — each with a one-sentence rationale aligned to MVP."
)
 
_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", _SYSTEM),
        (
            "human",
            "Requirement: {title}\n"
            "Vision features: {features}\n"
            "Constraints (optional): {constraints}\n"
            "Non-functionals (optional): {nfr}",
        ),
    ]
)
 
def make_chain(llm: Any, **knobs: Any) -> Runnable:
    """
    Map {title, features, constraints, nfr} -> TechnicalSolutionDraft.
    No numeric caps; keep freedom on modules/decisions/interfaces.
    Optional knobs reserved for future tweaks (e.g., allow_websocket=True).
    """
    defaults: Dict[str, Any] = {}
    if knobs:
        defaults.update(knobs)
    prompt = _PROMPT.partial(**defaults)
    return prompt | llm.with_structured_output(TechnicalSolutionDraft)
