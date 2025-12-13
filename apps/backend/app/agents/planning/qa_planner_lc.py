# apps/backend/app/agents/planning/qa_planner_lc.py

from __future__ import annotations
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import Runnable

from app.agents.lc.schemas import QASpec

try:
    from langchain_openai import ChatOpenAI  # type: ignore
except Exception:  # pragma: no cover
    ChatOpenAI = None  # type: ignore

_SYSTEM = (
    "You are the QA Planner for this run. Your job is to specify **what to test** and "
    "**how to verify behavior** without prescribing implementation details (paths, tools, or frameworks).\n\n"
    "OUTPUT CONTRACT\n"
    "- Return ONLY valid JSON matching the target schema (QASpec):\n"
    "  { \"scenarios\": [string, ...], \"checklist\": [string, ...] }\n"
    "- Do not include prose outside of JSON. No markdown, no comments.\n\n"
    "SCENARIOS (1–3)\n"
    "- Write short Gherkin scenarios that express observable behavior using Given/When/Then.\n"
    "- Tie behavior to the Story’s intent and its interfaces (e.g., function or API surface), "
    "not to file names or specific tools.\n"
    "- Prefer measurable outcomes (e.g., returned value, emitted event, HTTP status/body, state change) "
    "and include edge cases if relevant.\n\n"
    "CHECKLIST (3–8)\n"
    "- Provide terse, actionable unit-level checks as plain sentences (no Gherkin), each verifying a single assertion.\n"
    "- Keep these framework-neutral; do not mention testing libraries, runners, or file locations.\n"
    "- Where helpful, refer to **conceptual** targets (e.g., module/class/function names or API routes), "
    "not concrete repository paths.\n\n"
    "CONSTRAINTS\n"
    "- Do NOT prescribe file paths (e.g., __tests__/… or src/…); keep placement decisions conditional on repository conventions.\n"
    "- Do NOT name specific tools (Jest, Vitest, PyTest, Supertest, etc.).\n"
    "- Do NOT suggest code changes; specify expected behavior and verification only.\n\n"
    "FEEDBACK INCORPORATION\n"
    "- If prior feedback is provided, incorporate it directly into the scenarios and checklist. "
    "Treat feedback as authoritative corrections to scope, edge cases, and acceptance clarity.\n"
    "--- PRIOR FEEDBACK START ---\n{feedback_context}\n--- PRIOR FEEDBACK END ---\n"
)

_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", _SYSTEM),
        (
            "human",
            # Keep inputs the same; we’re explicit about their role:
            "Story title: {title}\n"
            "Story description (acceptance intent, user value): {description}\n"
            "Epic: {epic_title}\n"
            "Solution interfaces (public surface the implementation must honor): {interfaces}"
        ),
    ]
)

def make_chain(llm: BaseChatModel) -> Runnable:
    use_function_calling = False
    if ChatOpenAI is not None:
        try:
            if isinstance(llm, ChatOpenAI):
                use_function_calling = True
        except Exception:
            use_function_calling = False

    if use_function_calling:
        structured_llm = llm.with_structured_output(
            QASpec,
            method="function_calling",
        )
    else:
        structured_llm = llm.with_structured_output(
            QASpec,
            method="json_schema",
            strict=True,
        )

    return _PROMPT | structured_llm
