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
    "\n"
    "PRIMARY GOAL:\n"
    "- Define WHAT we are building and WHY, not HOW it will be implemented.\n"
    "- Your output will later be broken down into stories and tasks by other agents, so it must be clear, focused, and easy to implement.\n"
    "\n"
    "HARD LIMITS:\n"
    "- At most {max_goals} goals.\n"
    "- At most {max_personas} personas.\n"
    "- At most {max_features} prioritized features.\n"
    "\n"
    "STYLE:\n"
    "- Bullet points only.\n"
    "- One sentence per bullet.\n"
    "- Avoid marketing fluff, repetition, and vague statements.\n"
    "- Write in plain, concrete language that a developer can map to features without inventing extra behaviour.\n"
    "\n"
    "SCOPE:\n"
    "- MVP only.\n"
    "- Do NOT include roadmaps, phases, future work, or stretch goals.\n"
    "\n"
    "CONTENT RULES:\n"
    "- Personas: describe the target audience as archetypes or personality types the product is aimed at "
    "- Features: user-visible capabilities phrased as outcomes (what the user can do/see), not implementation details.\n"
    "- Goals: measurable outcomes (clarity, correctness, usability, reliability), not technical milestones.\n"
    "- Do NOT mention specific files, folders, classes, functions, or tools. Those belong to later implementation stages.\n"
    "\n"
    "COST-AWARE, IMPLEMENTATION-FRIENDLY VISION:\n"
    "- Define features so they can be implemented with a small, coherent set of changes rather than a broad refactor.\n"
    "- Prefer features that are focused and testable (e.g. 'Player can click a Randomize Fleet button to auto-place ships') over huge, multi-concern bundles.\n"
    "- Avoid fuzzy phrases like 'completely overhaul the UI' or 'rewrite the game engine'. Instead, describe specific behaviours and UX outcomes.\n"
    "- Each feature should describe a specific behaviour that can later be validated by actually using the app.\n"
    "\n"
    "TECHNOLOGY GUIDANCE:\n"
    "- Reflect explicit constraints from the requirement (e.g. 'browser-only', 'frontend-only') at a high level.\n"
    "- Do NOT prescribe repository paths, folder names, file names, CLI commands, libraries, or specific tools unless they are explicitly given in Constraints or Repo Conventions.\n"
    "- When repo conventions are provided, reference them GENERICALLY (e.g. 'follow the existing client/server separation') rather than naming concrete paths.\n"
    "\n"
    "EXEMPLAR / REFLECTION HINTS (optional):\n"
    "- The exemplar may contain your own prior outputs plus retrospective comments (e.g. 'Human:' / 'AI:' notes) about what worked well or poorly.\n"
    "- Treat any feedback inside the exemplar as your own design retrospective: these are improvements you have agreed to make to your future work.\n"
    "- Actively adopt this feedback to improve clarity, structure, and cost-awareness in THIS vision, rather than treating it as optional.\n"
    "- Do NOT copy exemplar content verbatim and do NOT quote or restate the feedback text itself.\n"
    "- Apply the feedback implicitly by producing a better artefact tailored to THIS requirement.\n"
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
    defaults: Dict[str, Any] = {"max_goals": 5, "max_personas": 5, "max_features": 10}
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
