# apps/backend/app/agents/planning/architect_lc.py
from __future__ import annotations
from typing import Any
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from app.agents.lc.schemas import TechnicalSolutionDraft

_SYSTEM = (
    "You are a Solution Architect. Propose a minimal, testable solution design. "
    "Guardrails: you MUST use Node + Vite + React + SQLite. "
    "Output stack, modules, interfaces (name->signature), and key decisions."
)

_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", _SYSTEM),
        (
            "human",
            "Requirement: {title}\n"
            "Vision features: {features}\n"
            "Constraints: {constraints}\n"
            "Non-functionals: {nfr}",
        ),
    ]
)

def make_chain(llm: Any) -> Runnable:
    """Returns a Runnable that maps {title, features, constraints, nfr} -> TechnicalSolutionDraft."""
    return _PROMPT | llm.with_structured_output(TechnicalSolutionDraft)
