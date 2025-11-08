# apps/backend/app/agents/planning/tech_writer_lc.py

from __future__ import annotations
from langchain_core.prompts import ChatPromptTemplate
from app.agents.lc.schemas import TechWritingBundleDraft, TaskDraft

# --- Design Notes ---

def make_notes_chain(llm):
    """
    Returns a chain that emits ONLY design notes (no tasks).
    Output is parsed as TechWritingBundleDraft but we only use .notes.
    """
    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You are a senior technical writer. Create concise design notes to guide implementation.\n"
         "STRICT RULES:\n"
         "- Output MUST be valid JSON for the Pydantic schema TechWritingBundleDraft (notes only).\n"
         "- Fill `notes` with 2–5 items. Do NOT include tasks here.\n"
         "- Each note MUST have: title, kind in {{overview,api,frontend,repo,quality,risk,other}}, body_md.\n"
         "- Use related_epic_titles and related_story_titles to link by EXACT TITLES from the provided lists.\n"),
        ("human",
         "Context:\n"
         "- Features: {features}\n"
         "- Stack: {stack}\n"
         "- Modules: {modules}\n"
         "- Interfaces: {interfaces}\n"
         "- Decisions: {decisions}\n"
         "- Epics: {epic_titles}\n"
         "- Stories: {story_titles}\n"
         "Return JSON ONLY."),
    ])
    # Force the structured shape via LC v1 structured output
    return prompt | llm.with_structured_output(TechWritingBundleDraft)

# --- Per-story Tasks ---

def make_tasks_chain(llm):
    """
    Returns a chain that, given a single story input, emits TaskDraft for THAT story.
    Orchestrator can batch() over stories.
    """
    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You are a pragmatic tech writer. Produce implementable, granular tasks that an engineer can execute.\n"
         "STRICT RULES:\n"
         "- Output MUST be valid JSON for the Pydantic schema TaskDraft.\n"
         "- story_title MUST equal the provided story_title EXACTLY.\n"
         "- items MUST be 5–10 atomic steps (no vague items like 'do the thing').\n"
         "- Prefer verbs like: scaffold, implement, wire, validate, handle error, write unit test.\n"
         "- Align tasks with acceptance criteria & interfaces.\n"),
        ("human",
         "Story:\n"
         "- story_title: {story_title}\n"
         "- description: {story_description}\n"
         "- epic_title: {epic_title}\n"
         "- interfaces: {interfaces}\n"
         "- acceptance_criteria (Gherkin snippets):\n{gherkin}\n"
         "Return JSON ONLY."),
    ])
    return prompt | llm.with_structured_output(TaskDraft)
