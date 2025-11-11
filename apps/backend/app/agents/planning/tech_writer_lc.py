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
    Optimized for Serena: minimal, atomic, code-centric steps; no tests/AC/design notes; no tool or code prescriptions.
    """
    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You are a Technical Writer producing a minimal task list for a coding agent named Serena.\n"
         "Objectives:\n"
         "• Use the FEWEST tasks needed to complete the story. If the story is already satisfied, return ZERO tasks.\n"
         "• Each task is ATOMIC and code-centric (one concrete action).\n"
         "• STRICTLY no scope creep: do not add unrelated work or future enhancements.\n\n"
         "Guardrails:\n"
         "• Output MUST be valid JSON for the Pydantic schema TaskDraft.\n"
         "• story_title MUST equal the provided story_title EXACTLY.\n"
         "• Do NOT include testing tasks, acceptance criteria, Gherkin/BDD, design notes, or documentation tasks.\n"
         "• Do NOT prescribe tools, commands, libraries, or exact code. Hint the outcome, not the implementation.\n"
         "• Prefer outcome verbs like: create, update, implement, wire, integrate, persist, handle, refactor (scoped), remove (scoped).\n"
         "• Keep each task to a single action; split if a second action would be required.\n"
         "• If a step cannot be executed without prior work, reorder or add the minimal prerequisite step only if it is part of this story.\n"),
        ("human",
         "Story Context:\n"
         "- story_title: {story_title}\n"
         "- description: {story_description}\n"
         "- epic_title: {epic_title}\n"
         "- relevant_interfaces (optional): {interfaces}\n"
         "- stack hint (do not prescribe tools): Node/Express backend, React + Zustand UI, SQLite, Vite tooling\n"
         "Return JSON ONLY."),
    ])
    return prompt | llm.with_structured_output(TaskDraft)
