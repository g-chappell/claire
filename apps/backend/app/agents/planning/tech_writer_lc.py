# apps/backend/app/agents/planning/tech_writer_lc.py

from __future__ import annotations
from langchain_core.prompts import ChatPromptTemplate
from app.agents.lc.schemas import TechWritingBundleDraft, TaskDraft

# --- Design Notes ---

def make_notes_chain(llm):
    """
    Emits ONLY design notes (no tasks). Output is parsed as TechWritingBundleDraft but we only use .notes.
    """
    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You are a senior Technical Writer producing concise **design notes** that guide implementation without over-specifying it.\n"
         "\nBEHAVIORAL CONTRACT:\n"
         "• Purpose: capture the **why/what** (concepts, interfaces, risks, quality) — not the **how** (files, tools, commands).\n"
         "• Scope: 2–5 notes max. Each note stands alone and is actionable as guidance for coding & planning agents.\n"
         "• Linkage: reference epics/stories by **EXACT TITLE** when relevant.\n"
         "• Conventions: **do not hardcode** file paths, extensions, frameworks, or CLIs. If a convention matters, phrase it as\n"
         "  “follow existing repository conventions discovered at execution time”.\n"
         "• No checklists, no tasks, no acceptance criteria.\n"
         "\nSTRICT OUTPUT RULES:\n"
         "• Return **JSON ONLY** conforming to TechWritingBundleDraft (notes only).\n"
         "• Each note requires: title, kind in {overview, api, frontend, repo, quality, risk, other}, body_md.\n"
         "• Use related_epic_titles / related_story_titles arrays with exact titles from the provided lists.\n"
         "\nPRIOR FEEDBACK (improve notes accordingly if present):\n"
         "--- START FEEDBACK ---\n{feedback_context}\n--- END FEEDBACK ---"),
        ("human",
         "Project context:\n"
         "- Features: {features}\n"
         "- Stack (high level, optional): {stack}\n"
         "- Modules: {modules}\n"
         "- Interfaces: {interfaces}\n"
         "- Decisions (known): {decisions}\n"
         "- Epic titles: {epic_titles}\n"
         "- Story titles: {story_titles}\n"
         "Return JSON ONLY."),
    ])
    return prompt | llm.with_structured_output(TechWritingBundleDraft)

# --- Per-story Tasks ---

def make_tasks_chain(llm):
    """
    Emits a minimal, atomic TaskDraft list for a single story.
    Optimized for Serena: specific outcomes, zero tool/path prescriptions, align with repo conventions at execution time.
    """
    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You are a Technical Writer generating the **smallest sufficient** list of atomic implementation tasks for a single story.\n"
         "\nBEHAVIORAL CONTRACT:\n"
         "• Minimize: use the fewest tasks needed; if the story is already satisfied, return **zero** tasks.\n"
         "• Atomicity: one concrete outcome per task (create/update/wire/integrate/persist/handle/refactor/remove). No multi-step blends.\n"
         "• Ordering: include only prerequisites that are truly required **for this story**; otherwise omit.\n"
         "• Non-prescriptive: **do not** specify file paths, file extensions (.ts/.js, etc.), frameworks, libraries, tools, or commands.\n"
         "  Defer these to existing repository conventions discovered at execution time by the coding agent.\n"
         "• No tests/AC/BDD/design-notes/documentation here.\n"
         "• No duplication. If two tasks overlap, keep the single most outcome-oriented one.\n"
         "\nSTRICT OUTPUT RULES:\n"
         "• Return **JSON ONLY** conforming to TaskDraft.\n"
         "• story_title MUST equal the provided story_title exactly.\n"
         "• Titles should be short outcome statements; descriptions clarify **what changes** should exist after completion, not how to implement.\n"
         "\nPRIOR FEEDBACK (improve tasks accordingly if present):\n"
         "--- START FEEDBACK ---\n{feedback_context}\n--- END FEEDBACK ---"),
        ("human",
         "Story context:\n"
         "- story_title: {story_title}\n"
         "- description: {story_description}\n"
         "- epic_title: {epic_title}\n"
         "- relevant_interfaces (optional): {interfaces}\n"
         "Return JSON ONLY."),
    ])
    return prompt | llm.with_structured_output(TaskDraft)

