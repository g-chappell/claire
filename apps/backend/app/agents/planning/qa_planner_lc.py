# apps/backend/app/agents/planning/qa_planner_lc.py

from __future__ import annotations
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import Runnable

from app.agents.lc.schemas import QASpec

_SYSTEM = (
    "You are a QA Planner. For the given Story, produce JSON that conforms to the target schema with two fields:\n"
    "- scenarios: array of 1–3 short Gherkin scenarios (strings)\n"
    "- checklist: array of 3–8 unit test checks (strings)\n"
    "Return ONLY valid JSON; no prose."
)

_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", _SYSTEM),
        (
            "human",
            "Story title: {title}\n"
            "Story description: {description}\n"
            "Epic: {epic_title}\n"
            "Solution interfaces: {interfaces}"
        ),
    ]
)

def make_chain(llm: BaseChatModel) -> Runnable:
    return _PROMPT | llm.with_structured_output(QASpec)
