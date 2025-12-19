#apps/backend/app/agents/planning/vision_lc.py

from typing import Any, Dict
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
 
from app.agents.lc.schemas import ProductVisionDraft

# Optional: used only to detect OpenAI for structured-output mode switching
try:
    from langchain_openai import ChatOpenAI  # type: ignore
except Exception:  # pragma: no cover
    ChatOpenAI = None  # type: ignore
 
_SYSTEM = (
    "You are a Product Manager for software development, producing a concise Product Vision as structured JSON.\n"
    "Goal: define *what* we are building and *why*—NOT *how* it will be implemented.\n"
    "Hard caps: ≤{max_goals} goals, ≤{max_personas} personas, ≤{max_features} prioritized features.\n"
    "Style: bullet points only; one sentence per bullet; avoid marketing fluff, repetition, and vague statements.\n"
    "Scope: MVP only. Do not include roadmaps, phases, future work, or stretch goals.\n"
    "Content rules:\n"
    "- Personas: real user types (e.g., 'Player', 'Admin'), not internal roles (e.g., 'Developer').\n"
    "- Features: user-visible capabilities, phrased as outcomes; avoid implementation details.\n"
    "- Goals: measurable outcomes (clarity, correctness, usability), not technical milestones.\n"
    "Technology guidance: reflect constraints (if any), but do NOT prescribe repository paths, folder names, file names, CLI commands, or specific tools unless explicitly given in Constraints or Repo Conventions.\n"
    "When repo conventions are provided, reference them *generically* (e.g., “follow the existing client/server separation”) rather than naming concrete paths.\n"
    "\n"
    "EXEMPLAR / FEEDBACK HINTS (optional):\n"
    "- The exemplar may contain prior feedback such as 'Human:' / 'AI:' notes or critiques.\n"
    "- Treat any feedback inside the exemplar as guidance on *quality and structure* (what to improve/avoid).\n"
    "- Do NOT copy exemplar content. Do NOT quote or repeat feedback text in your output.\n"
    "- Apply the feedback implicitly by producing a better artefact for THIS requirement.\n"
    "--- EXEMPLAR START ---\n{exemplar}\n--- EXEMPLAR END ---\n"
    "\n"
    "REPO CONVENTIONS (optional, summarize not prescribe):\n{repo_conventions}\n"
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
            "Checklist before you answer: MVP-only, no implementation details, obey caps.\n"
            "Return JSON ONLY that matches the ProductVisionDraft schema."
        ),
    ]
)
 
def make_chain(llm: Any, **knobs: Any) -> Runnable:
    defaults: Dict[str, Any] = {"max_goals": 3, "max_personas": 2, "max_features": 5}
    if knobs:
        defaults.update(knobs)
    # ensure placeholders exist even if not passed
    defaults.setdefault("exemplar", "")
    defaults.setdefault("repo_conventions", "")
    prompt = _PROMPT.partial(**defaults)

    use_function_calling = False
    if ChatOpenAI is not None:
        try:
            if isinstance(llm, ChatOpenAI):
                use_function_calling = True
        except Exception:
            use_function_calling = False

    if use_function_calling:
        structured_llm = llm.with_structured_output(
            ProductVisionDraft,
            method="function_calling",
        )
    else:
        structured_llm = llm.with_structured_output(
            ProductVisionDraft,
            method="json_schema",
            strict=True,
        )

    return prompt | structured_llm
