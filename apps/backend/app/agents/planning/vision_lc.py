#apps/backend/app/agents/planning/vision_lc.py

from typing import Any, Dict
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
 
from app.agents.lc.schemas import ProductVisionDraft
 
_SYSTEM = (
    "You are a Product Manager for software development, producing a concise Product Vision as structured JSON.\n"
    "Goal: define *what* we are building and *why*—NOT *how* it will be implemented.\n"
    "Hard caps: ≤{max_goals} goals, ≤{max_personas} personas, ≤{max_features} prioritized features.\n"
    "Style: bullet points only; one sentence per bullet; avoid marketing fluff and repetition.\n"
    "Scope: MVP only. Do not include roadmaps, phases, or future work.\n"
    "Technology guidance: reflect constraints (if any), but do NOT prescribe repository paths, folder names, file names, CLI commands, or specific tools unless they are explicitly given in Constraints or Repo Conventions.\n"
    "When repo conventions are provided, reference them *generically* (e.g., “follow the existing client/server separation”) rather than naming concrete paths.\n"
    "Prior feedback: Incorporate only actionable items from human/AI feedback below. Do not reintroduce deprecated choices or contradict current constraints.\n"
    "\n"
    "CONTEXT:\n"
    "--- PRIOR FEEDBACK START ---\n{feedback_context}\n--- PRIOR FEEDBACK END ---\n"
    "--- HUMAN CONTEXT (optional) ---\n{human_context}\n"
    "--- REPO CONVENTIONS (optional, summarize not prescribe) ---\n{repo_conventions}\n"
)
 
_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", _SYSTEM),
        (
            "human",
            "Requirement ID: {req_id}\n"
            "Title: {title}\n"
            "Description:\n{description}\n"
            "Constraints: {constraints}\n"
            "Non-functionals: {nfr}\n"
            "\n"
            "Return JSON ONLY that matches the ProductVisionDraft schema."
        ),
    ]
)
 
def make_chain(llm: Any, **knobs: Any) -> Runnable:
    defaults: Dict[str, Any] = {"max_goals": 3, "max_personas": 2, "max_features": 5}
    if knobs:
        defaults.update(knobs)
    # ensure placeholders exist even if not passed
    defaults.setdefault("feedback_context", "")
    defaults.setdefault("human_context", "")
    defaults.setdefault("repo_conventions", "")
    prompt = _PROMPT.partial(**defaults)
    return prompt | llm.with_structured_output(ProductVisionDraft)
