from __future__ import annotations
from langchain_core.prompts import ChatPromptTemplate
from app.agents.lc.schemas import QASpec

_SYSTEM = (
    "You are a QA Planner. For the given Story, write 1-3 Gherkin scenarios and a brief unit test checklist. "
    "Return BOTH fields as JSON arrays of strings (not a single string). "
    "Scenarios should be concise and observable."
)
_PROMPT = ChatPromptTemplate.from_messages([
    ("system", _SYSTEM),
    ("human", "Story title: {title}\nStory description: {description}\nEpic: {epic_title}\nSolution interfaces: {interfaces}")
])

def make_chain(llm):
    return _PROMPT | llm.with_structured_output(QASpec)
