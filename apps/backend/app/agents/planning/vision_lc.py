from __future__ import annotations
from langchain_core.prompts import ChatPromptTemplate
from app.agents.lc.schemas import ProductVisionDraft

_SYSTEM = (
    "You are a Product Manager. Create a concise Product Vision from the requirement: "
    "include goals, target personas, and a prioritized feature list. Keep bullets short."
)
_PROMPT = ChatPromptTemplate.from_messages([
    ("system", _SYSTEM),
    ("human", "Requirement ID: {req_id}\nTitle: {title}\nDescription:\n{description}\nConstraints: {constraints}\nNon-functionals: {nfr}")
])

def make_chain(llm):
    return _PROMPT | llm.with_structured_output(ProductVisionDraft)
