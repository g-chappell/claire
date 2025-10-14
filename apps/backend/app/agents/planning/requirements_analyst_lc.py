from __future__ import annotations
from langchain_core.prompts import ChatPromptTemplate
from app.agents.lc.schemas import RAPlanDraft

SYS = """You are a Requirements Analyst on an Agile team.
Given product features and a proposed technical solution, produce:
- Epics: 3–6 clear thematic groupings (title, short description).
- Stories: 4–12 user stories mapped to epics (each story must include epic_title, title, short description).
Rules:
- Return at least 1 Story per Epic.
- Keep titles concise and implementation-ready.
- Do NOT include IDs; titles only.
- Respond ONLY with the structured object requested by the tool; no extra keys.
"""

HUMAN = """Context
Features: {features}
Modules: {modules}
Interfaces: {interfaces}
Decisions: {decisions}

Output constraints:
- >= 3 epics total
- >= 1 story per epic
- 4–12 stories overall
"""

def make_chain(llm):
    structured = llm.with_structured_output(RAPlanDraft)
    prompt = ChatPromptTemplate.from_messages([("system", SYS), ("human", HUMAN)])
    return prompt | structured
