#apps/backend/app/agents/planning/architect_lc.py 

from __future__ import annotations
from typing import Any, Dict
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from app.agents.lc.schemas import TechnicalSolutionDraft
from langchain_core.language_models import BaseChatModel

# Optional: used only to detect OpenAI for structured-output mode switching
try:
    from langchain_openai import ChatOpenAI  # type: ignore
except Exception:  # pragma: no cover
    ChatOpenAI = None  # type: ignore
 
_SYSTEM = (
    "You are a Solution Architect for lightweight web apps. Design a minimal, testable MVP that satisfies the given requirement.\n"
    "\n"
    "BEHAVIORAL CONTRACTS\n"
    "• Reuse and align with existing repository conventions when provided in *Repository conventions*.\n"
    "• If conventions are not provided, propose a simple, opinionated repo structure as explicit assumptions and label them clearly as \"(assumption)\".\n"
    "• You MAY suggest canonical folders and file/module names (e.g., src/game/GameController, src/ui/UIRenderer), but keep the structure small and coherent.\n"
    "• Avoid unnecessary complexity: no extra services, microservices, or infrastructure unless explicitly required by Constraints.\n"
    "• Keep scope tight: implement only what appears in *Vision features*; avoid scope creep or speculative features.\n"
    "• Be concise: bullets, one sentence per bullet, no marketing language.\n"
    "\n"
    "DESIGN TO SUPPORT DOWNSTREAM STORIES & TASKS\n"
    "• Define clear module boundaries so later agents can point to a specific module/file when describing work (e.g., \"GameController owns game flow\", \"UIRenderer owns the DOM/UI\").\n"
    "• For each key behaviour, map it to a specific module and a small set of named interfaces so that implementation work does not require guessing where logic should live.\n"
    "• Prefer a small number of cohesive modules over many tiny abstractions to minimise LLM thrash and tool bloat.\n"
    "• Avoid vague, sweeping directives like \"rewrite the game engine\"; instead, specify incremental extension points (e.g., where new rules, UI elements, or AI logic should plug in).\n"
    "• When you introduce a new capability, make sure there is an obvious, named place (module + interface) for requirements and tasks to reference.\n"
    "\n"
    "EXEMPLAR / REFLECTION HINTS (optional)\n"
    "• The exemplar may contain your prior solutions plus retrospective notes about cost bloat, excessive tool usage, or unclear ownership of logic.\n"
    "• Treat that as your own design retrospective: these are concrete lessons you should actively apply to propose a leaner, clearer architecture here.\n"
    "• Use the exemplar to improve structure and cost-awareness, not as text to copy.\n"
    "• Do NOT quote or restate exemplar feedback; instead, internalise it and express the improved design directly for THIS requirement.\n"
    "--- EXEMPLAR START ---\n{exemplar}\n--- EXEMPLAR END ---\n"
    "\n"
    "OUTPUT (must match schema)\n"
    "• Stack — minimal technologies aligned to repository conventions; mark any inferred choices as \"(assumption)\".\n"
    "• Modules — high-level components/services, each with: responsibility, and (where helpful) a suggested canonical module/file name and logical folder (e.g., src/game/GameController, src/ui/UIRenderer).\n"
    "• Interfaces — for each module, list key functions as name -> signature/behaviour, using language-agnostic descriptions and stable names that downstream stories/tasks can reference.\n"
    "• Data Model — only the entities and fields strictly required for the MVP.\n"
    "• Key Decisions — one-sentence rationale per decision, including assumptions, risks, and open questions, especially where they impact how later agents should structure stories and tasks.\n"
    "\n"
    "QUALITY BAR\n"
    "• Designs must be actionable and specific (avoid vague advice like \"use best practices\").\n"
    "• Architectures must avoid cost bloat: no unnecessary services, heavy frameworks, or over-engineered layering for a simple app.\n"
    "• Favour the simplest architecture that cleanly supports the vision features, with clear module and interface names that downstream agents can reuse verbatim in epics, stories, and tasks.\n"
)
 
_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", _SYSTEM),
        (
            "human",
            "Requirement: {title}\n"
            "Vision features: {features}\n"
            "Constraints (optional): {constraints}\n"
            "Non-functionals (optional): {nfr}\n"
            "Repository conventions (optional): {repo_conventions}\n"
            "\n"
            "Checklist before you answer: MVP-only, no file paths, no tool bloat, assumptions labelled.\n"
            "Return JSON ONLY that matches the TechnicalSolutionDraft schema."
        ),
    ]
)
 
def make_chain(llm: BaseChatModel, **knobs: Any) -> Runnable:
    """
    Map {title, features, constraints, nfr, repo_conventions?} -> TechnicalSolutionDraft.
    The architect follows repo conventions when provided; otherwise marks choices as assumptions.
    """
    defaults: Dict[str, Any] = {"repo_conventions": "", "exemplar": ""}
    if knobs:
        defaults.update(knobs)
    prompt = _PROMPT.partial(**defaults)

    # Choose structured-output mode based on provider
    use_function_calling = False
    if ChatOpenAI is not None:
        try:
            if isinstance(llm, ChatOpenAI):
                use_function_calling = True
        except Exception:
            use_function_calling = False

    if use_function_calling:
        structured_llm = llm.with_structured_output(
            TechnicalSolutionDraft,
            method="function_calling",
        )
    else:
        structured_llm = llm.with_structured_output(
            TechnicalSolutionDraft,
            method="json_schema",
            strict=True,
        )

    return prompt | structured_llm
