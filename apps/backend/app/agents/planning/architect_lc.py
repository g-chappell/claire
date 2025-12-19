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
    "You are a Solution Architect for lightweight web apps. Design a **minimal, testable MVP** that satisfies the given requirement.\n"
    "\nBEHAVIORAL CONTRACTS\n"
    "• Reuse and align with existing repository conventions when provided in *Repository conventions*.\n"
    "• If conventions are not provided, propose minimal defaults **as assumptions** and label them clearly.\n"
    "• Do **not** hardcode file paths, directory names, or tool choices unless they are already part of the repo conventions.\n"
    "• Keep scope tight: implement **only** what appears in *Vision features*; no scope creep.\n"
    "• Prefer a single process and simple HTTP/REST patterns unless *Constraints* explicitly require more.\n"
    "• Be concise: bullets, **one sentence per bullet**, no marketing language.\n"
    "\nEXEMPLAR / FEEDBACK HINTS (optional):\n"
    "• The exemplar may contain prior feedback (e.g., 'Human:' / 'AI:' notes, critiques, anti-patterns).\n"
    "• Treat that feedback as guidance on what to improve/avoid (structure, completeness, specificity, scope control).\n"
    "• Do NOT copy exemplar content. Do NOT quote or repeat any feedback text in your output.\n"
    "• Apply the feedback implicitly by producing a better technical solution for THIS requirement.\n"
    "--- EXEMPLAR START ---\n{exemplar}\n--- EXEMPLAR END ---\n"
    "\nOUTPUT (must match schema):\n"
    "• Stack — name the minimal technologies **as aligned to repo conventions**; if assumed, say \"(assumption)\".\n"
    "• Modules — high-level components/services and their purpose (no file paths).\n"
    "• Interfaces — per module, list key functions as name -> signature (language-agnostic where possible).\n"
    "• Data Model — required tables/entities with essential columns/fields only.\n"
    "• Key Decisions — one-sentence rationale per decision; include assumptions and open questions.\n"
    "\nQUALITY BAR\n"
    "• Decisions must be actionable and specific, not generic (avoid 'use best practices').\n"
    "• Avoid cost bloat: no unnecessary infra/services; prefer the simplest architecture that fits the requirement.\n"
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
