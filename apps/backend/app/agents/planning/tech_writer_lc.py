# apps/backend/app/agents/planning/tech_writer_lc.py

from __future__ import annotations
from langchain_core.prompts import ChatPromptTemplate
from app.agents.lc.schemas import TechWritingBundleDraft, TaskDraft

try:
    from langchain_openai import ChatOpenAI  # type: ignore
except Exception:  # pragma: no cover
    ChatOpenAI = None  # type: ignore

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
            "• Execution economics: avoid notes that encourage extra tooling, spikes, or speculative refactors unless explicitly required.\n"
            "\nSTRICT OUTPUT RULES:\n"
            "• Return **JSON ONLY** conforming to TechWritingBundleDraft (notes only).\n"
            "• Each note requires: title, kind in {overview, api, frontend, repo, quality, risk, other}, body_md.\n"
            "• Use related_epic_titles / related_story_titles arrays with exact titles from the provided lists.\n"
            "\nEXEMPLAR / FEEDBACK HINTS (optional):\n"
            "• The exemplar may contain prior feedback (e.g., 'Human:' / 'AI:' notes, critiques, anti-patterns).\n"
            "• Treat it as guidance on what to improve/avoid (scope control, too many notes, over-specification, tool-churn, vague guidance).\n"
            "• Do NOT copy exemplar content. Do NOT quote or repeat any feedback text in your output.\n"
            "• Apply feedback implicitly by writing better notes for THIS requirement.\n"
            "--- EXEMPLAR START ---\n{exemplar}\n--- EXEMPLAR END ---"
        ),
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
    use_function_calling = False
    if ChatOpenAI is not None:
        try:
            if isinstance(llm, ChatOpenAI):
                use_function_calling = True
        except Exception:
            use_function_calling = False

    if use_function_calling:
        structured_llm = llm.with_structured_output(
            TechWritingBundleDraft,
            method="function_calling",
        )
    else:
        structured_llm = llm.with_structured_output(
            TechWritingBundleDraft,
            method="json_schema",
            strict=True,
        )

    return prompt | structured_llm

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
            "• Avoid tool-churn: do NOT create tasks like “research”, “investigate”, “spike”, “choose library”, “set up tooling”,\n"
            "  “add logging everywhere”, or “refactor for cleanliness” unless the story explicitly requires it.\n"
            "• Atomicity: one concrete outcome per task (create/update/wire/integrate/persist/handle/remove). No multi-step blends.\n"
            "• Ordering (authoritative): every task MUST include priority_rank (1..K, gap-free, 1 = highest); the app will **not** reorder.\n"
            "• Dependencies: include depends_on only for true prerequisites within the same story; use exact task titles.\n"
            "• Dependency correctness: depends_on must reference tasks that exist AND appear earlier in priority_rank (no cycles).\n"
            "• Within a story, follow bottom-up sequencing: create/initialize → wire controllers/state/persistence → render → UX/diagnostics.\n"
            "• Non-prescriptive: **do not** specify file paths, file extensions, frameworks, libraries, tools, or commands.\n"
            "• If acceptance criteria (gherkin) are provided, align tasks to satisfy them with minimal work.\n"
            "\nSTRICT OUTPUT RULES:\n"
            "• Return **JSON ONLY** conforming to TaskDraft.\n"
            "• Required per task: title, description, priority_rank (int, 1 = highest), depends_on.\n"
            "• story_title MUST equal the provided story_title exactly.\n"
            "• Titles should be short outcome statements; descriptions clarify **what changes** should exist after completion, not how.\n"
            "\nEXEMPLAR / FEEDBACK HINTS (optional):\n"
            "• The exemplar may contain prior feedback (e.g., critiques about cost bloat, too many tasks, excessive tool usage).\n"
            "• Use it as guidance to reduce bloat and improve ordering/dependencies for THIS story.\n"
            "• Do NOT copy exemplar content. Do NOT quote or repeat any feedback text in your output.\n"
            "--- EXEMPLAR START ---\n{exemplar}\n--- EXEMPLAR END ---"
        ),
        ("human",
            "Story context:\n"
            "- story_title: {story_title}\n"
            "- description: {story_description}\n"
            "- epic_title: {epic_title}\n"
            "- relevant_interfaces (optional): {interfaces}\n"
            "- acceptance_criteria_gherkin (optional): {gherkin}\n"
            "Return JSON ONLY."),
    ]).partial(exemplar="", gherkin="")
    use_function_calling = False
    if ChatOpenAI is not None:
        try:
            if isinstance(llm, ChatOpenAI):
                use_function_calling = True
        except Exception:
            use_function_calling = False

    if use_function_calling:
        structured_llm = llm.with_structured_output(
            TaskDraft,
            method="function_calling",
        )
    else:
        structured_llm = llm.with_structured_output(
            TaskDraft,
            method="json_schema",
            strict=True,
        )

    return prompt | structured_llm

