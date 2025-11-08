# apps/backend/app/agents/planning/vision_lc.py
from __future__ import annotations

from typing import Any
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable

from app.agents.lc.schemas import ProductVisionDraft

_SYSTEM = (
    "You are a Product Manager. Create a concise Product Vision from the requirement: "
    "include goals, target personas, and a prioritized feature list. Keep bullets short."
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


def make_chain(llm: Any) -> Runnable:
    """Build a v1 LangChain runnable that returns a ProductVisionDraft."""
    return _PROMPT | llm.with_structured_output(ProductVisionDraft)
