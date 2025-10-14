from __future__ import annotations
from langchain_core.prompts import ChatPromptTemplate
from app.agents.lc.schemas import TechnicalSolutionDraft

_SYSTEM = (
    "You are a Solution Architect. Propose a minimal, testable solution design. "
    "Guardrails: you MUST use Node + Vite + React + SQLite. "
    "Output stack, modules, interfaces (name->signature), and key decisions."
)
_PROMPT = ChatPromptTemplate.from_messages([
    ("system", _SYSTEM),
    ("human", "Requirement: {title}\nVision features: {features}\nConstraints: {constraints}\nNon-functionals: {nfr}")
])

def make_chain(llm):
    return _PROMPT | llm.with_structured_output(TechnicalSolutionDraft)
