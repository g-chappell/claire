from __future__ import annotations
from langchain_core.prompts import ChatPromptTemplate
from app.agents.lc.schemas import RAPlanDraft

_SYSTEM = (
    "You are a Requirements Analyst. From the Vision and Solution, create Epics and Stories. "
    "Each story should map to exactly one epic (use epic_title to reference). "
    "Keep titles crisp; descriptions are short rationale."
)
_PROMPT = ChatPromptTemplate.from_messages([
    ("system", _SYSTEM),
    ("human", "Vision features: {features}\nModules: {modules}\nInterfaces: {interfaces}\nDecisions: {decisions}")
])

def make_chain(llm):
    return _PROMPT | llm.with_structured_output(RAPlanDraft)
