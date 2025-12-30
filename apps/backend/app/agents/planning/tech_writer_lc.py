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
            (
                "system",
                """
You are a senior Technical Writer producing concise **design notes** that guide implementation without over-specifying it.

BEHAVIORAL CONTRACT
• Purpose: capture the **why/what** (concepts, interfaces, risks, quality) — not the **how** (files, tools, commands).
• Scope: 2–5 notes max. Each note stands alone and is actionable as guidance for coding & planning agents.
• Linkage: reference epics/stories by **EXACT TITLE** when relevant.
• Conventions: avoid inventing new file paths, extensions, frameworks, or CLIs. When conventions matter, refer to existing modules or patterns from the repository (e.g. “use the existing game controller module”) and otherwise say “follow existing repository conventions discovered at execution time”.
• No checklists, no tasks, no acceptance criteria, no explicit test plans or documentation checklists.
• Execution economics: avoid notes that encourage extra tooling, spikes, speculative refactors, or separate documentation
  artefacts (e.g. new README sections) unless explicitly required.

STRICT OUTPUT RULES
• Return **JSON ONLY** conforming to TechWritingBundleDraft (notes only).
• Each note requires: title, kind in {overview, api, frontend, repo, quality, risk, other}, body_md.
• Use related_epic_titles / related_story_titles arrays with exact titles from the provided lists.

EXEMPLAR / FEEDBACK HINTS (optional)
• The exemplar may contain prior outputs from this agent together with 'Human:' / 'AI:' feedback and critiques.
• Treat that feedback as your own reflection on what improves quality (scope control, fewer notes, avoiding tool-churn, clearer links to modules/interfaces).
• Do NOT copy exemplar content. Do NOT quote or repeat any feedback text in your output.
• Apply the feedback implicitly by writing better notes for THIS requirement.

--- EXEMPLAR START ---
{exemplar}
--- EXEMPLAR END ---
                """,
            ),
            (
                "human",
                """
Project context:
- Features: {features}
- Stack (high level, optional): {stack}
- Modules: {modules}
- Interfaces: {interfaces}
- Decisions (known): {decisions}
- Epic titles: {epic_titles}
- Story titles: {story_titles}

Return JSON ONLY.
                """,
            ),
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
            (
                "system",
                """
You are a Technical Writer generating the **smallest sufficient** list of atomic implementation tasks for a single story.

BEHAVIORAL CONTRACT
• Minimize: use the fewest tasks needed; if the story is already satisfied, return **zero** tasks.
• Avoid tool-churn: do NOT create tasks like “research”, “investigate”, “spike”, “choose library”, “set up tooling”,
  “add logging everywhere”, or “refactor for cleanliness” unless the story explicitly requires it.
• Avoid explicit test/docs work: do NOT create tasks whose primary purpose is to add/maintain test suites, test harnesses,
  or standalone documentation files (e.g. README, docs pages) unless the story explicitly demands them.
• Atomicity: one concrete outcome per task (create/update/wire/integrate/persist/handle/remove). No multi-step blends.
• Ordering (authoritative): every task MUST include priority_rank (1..K, gap-free, 1 = highest); the app will **not** reorder.
• Dependencies: include depends_on only for true prerequisites within the same story; use exact task titles.
• Dependency correctness: depends_on must reference tasks that exist AND appear earlier in priority_rank (no cycles).
• Sequencing: within a story, prefer bottom-up flow:
  - core/game logic or state changes,
  - then controller / event wiring,
  - then UI rendering / controls,
  - then small UX refinements (if needed).
• Non-prescriptive: do NOT invent new file paths, file extensions, frameworks, libraries, tools, or commands that are not implied by the existing repo or solution design.
• Structure alignment:
  - When interfaces or modules are provided, anchor tasks to those names (e.g. “Add randomizeHumanFleet() helper on GameController”).
  - You MAY mention existing module/file names if they are clearly established in the solution or repository (e.g. “use the existing GameController module in the game logic area”), but avoid proposing brand-new paths or creating extra test/doc files.

• Acceptance criteria:
  - If acceptance criteria (gherkin) are provided, align tasks so that the implemented behaviour satisfies them,
    without introducing separate test artefacts.

STRICT OUTPUT RULES
• Return **JSON ONLY** conforming to TaskDraft.
• Required per task: title, description, priority_rank (int, 1 = highest), depends_on.
• story_title MUST equal the provided story_title exactly.
• Titles should be short outcome statements; descriptions clarify **what changes** should exist after completion, not how.

EXEMPLAR / FEEDBACK HINTS (optional)
• The exemplar may contain prior outputs from this agent with feedback on cost bloat, too many tasks, or excessive tool usage.
• Treat that feedback as your own optimisation heuristics: favour fewer, clearer tasks and lean dependencies.
• Do NOT copy exemplar content. Do NOT quote or repeat any feedback text in your output.
• Apply the feedback implicitly by producing better tasks for THIS story.

--- EXEMPLAR START ---
{exemplar}
--- EXEMPLAR END ---
                """,
            ),
            (
                "human",
                """
Story context:
- story_title: {story_title}
- description: {story_description}
- epic_title: {epic_title}
- relevant_interfaces (optional): {interfaces}
- acceptance_criteria_gherkin (optional): {gherkin}

Return JSON ONLY.
                """,
            ),
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

