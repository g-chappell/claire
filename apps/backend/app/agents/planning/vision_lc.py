#apps/backend/app/agents/planning/vision_lc.py

from typing import Any, Dict
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
 
from app.agents.lc.schemas import ProductVisionDraft
 
_SYSTEM = (
    "You are a Product Manager for Software Development, focused on building lightweight web applications. Produce a concise Product Vision as structured JSON."
    "\nKeep it **simple** and MVP-scoped."
    "\nHard caps: ≤{max_goals} goals, ≤{max_personas} personas, ≤{max_features} prioritized features."
    "\nStyle: bullet points only; **one sentence per bullet**; avoid marketing language and repetition."
    "\nDo **not** include roadmaps, phases, or future work."
    "\nAvoid advanced/speculative tech unless it appears explicitly in *Constraints*."
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
            "Non-functionals: {nfr}",
        ),
    ]
)
 
 

def make_chain(llm: Any, **knobs: Any) -> Runnable:
    """
    Build a v1 LangChain runnable that returns a ProductVisionDraft.
    Tweak caps via kwargs: max_goals, max_personas, max_features.
    """
    defaults: Dict[str, Any] = {"max_goals": 3, "max_personas": 2, "max_features": 5}
    if knobs:
        defaults.update(knobs)  # knobs is a dict[str, Any] at runtime
    prompt = _PROMPT.partial(**defaults)
    return prompt | llm.with_structured_output(ProductVisionDraft)
