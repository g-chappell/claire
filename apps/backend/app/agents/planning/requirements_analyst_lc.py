# apps/backend/app/agents/planning/requirements_analyst_lc.py

from __future__ import annotations
from typing import Any, Dict
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from app.agents.lc.schemas import RAPlanDraft

# Optional: only used to detect OpenAI for structured-output method switching
try:
    from langchain_openai import ChatOpenAI  # type: ignore
except Exception:  # pragma: no cover
    ChatOpenAI = None  # type: ignore

_SYS = """You are a Requirements Analyst on an Agile Software Delivery team.
Goal: produce **MVP-sized** Epics and Stories that a single coding agent can implement iteratively.

Principles
• Shippable epics: each epic must be a demoable increment (e.g., "App scaffold (baseline)", "Feature X end-to-end").
• No scope creep: use only the items present in *Vision features*. Do not invent features or expand scope.
• Keep it concise: one sentence per description; verb-first titles.
• Avoid proliferation: choose the **fewest** epics/stories that satisfy the Vision.
  Soft caps (ceilings, not targets): ≤{max_epics} epics, ≤{max_stories_total} stories overall, ≤{max_stories_per_epic} per epic.

Execution economics (MANDATORY)
• Plan for a single coding agent: fewer, larger, coherent stories beats many tiny stories.
• Minimize tool usage and churn: avoid stories that exist only to “research”, “spike”, “explore options”, “set up tooling”, or “refactor”.
• Prefer “vertical slices” that deliver working increments (end-to-end thin flow) over horizontal micro-tasks.

Ordering (authoritative):
• You MUST assign priority_rank (1..K, gap-free, 1 = highest) for every epic and for every story within its epic.
• The app will NOT reorder; your ranks determine execution order.

Dependencies:
• Provide depends_on for true prerequisites.
• For epics, depends_on is a list of other **epic titles** from this draft (use titles, not IDs).
• For stories, depends_on is a list of other **story titles** from the same epic (use titles, not IDs).
• When you reference another epic/story, copy its title text exactly so it can be matched (case-insensitive).
• Dependencies must be consistent with ranks (a story cannot depend on a lower-priority story).

Bottom-Up Build Philosophy (MANDATORY for ranking + dependencies):
1) Scaffold & baseline (MUST be Epic #1): file structure, placeholders, module boundaries, initialization wiring.
2) Core state & adapters: state manager, storage adapters, persistence surfaces.
3) Controllers & cross-module event wiring.
4) UI render pipeline & visuals.
5) UX polish & diagnostics.
6) Feature iterations on top of the stable base.

Behavioral contract for stories
• Each story description states intended behavior + observable outcome (“Do <X>; Done when <Y>”).
• Reference capabilities at the **conceptual layer** (Backend/API, Frontend/UI, Data/Storage, Tests), not concrete files or tools.
• If Proposed Solution names interfaces/modules/boundaries, anchor stories to those names; keep implementation details conditional on repo conventions.

Output format (STRICT):
   • For each epic (REQUIRED fields): title, description, priority_rank (int, 1..K), depends_on (array of epic titles in this draft; [] if none).
   • For each story (REQUIRED fields): epic_title, title, description, priority_rank (int, 1..K within that epic), depends_on (array of story titles **from the same epic**; [] if none).

Rules:
   • You MUST assign a unique, gap-free priority_rank per epic and per story-in-epic.
   • You MUST include depends_on arrays (use titles, not IDs). Cross-epic story deps are forbidden.
   • Story deps must reference titles that exist in the same epic and appear earlier in rank order.

EXEMPLAR / FEEDBACK HINTS (optional):
• The exemplar may contain prior feedback (e.g., 'Human:' / 'AI:' notes, critiques, anti-patterns).
• Treat that feedback as guidance on what to improve/avoid (scope control, number of epics/stories, dependency correctness, ordering, avoiding cost/tool bloat).
• Do NOT copy exemplar content. Do NOT quote or repeat any feedback text in your output.
• Apply the feedback implicitly by producing a better RA plan for THIS requirement.

--- EXEMPLAR START ---
{exemplar}
--- EXEMPLAR END ---
"""

_HUMAN = """Context
Vision Features: {features}
Proposed Solution — Modules: {modules}
Proposed Solution — Interfaces: {interfaces}
Proposed Solution — Decisions: {decisions}

Guidance
• Choose epics that map to coherent, shippable increments (scaffold or one end-to-end feature).
• Write stories as concrete behavioral slices expressed in conceptual layers (Backend/API, Frontend/UI, Data/Storage, Tests).
• If the Proposed Solution names interfaces/modules/boundaries, anchor stories to those names; otherwise use generic layer names.
• Maintain bottom-up order within each epic: scaffold → backend slice → UI slice → test/verification.

Pre-flight checks (do these before you answer)
• Epic #1 is scaffold/baseline, priority_rank=1, depends_on=[].
• Every epic has priority_rank 1..K gap-free.
• Within each epic, story priority_rank is 1..K gap-free.
• Every depends_on list uses titles that exist and are ranked earlier.
• Avoid bloat: prefer fewer stories that deliver vertical slices.
Return JSON ONLY that matches the RAPlanDraft schema.
"""

def make_chain(llm: Any, **knobs: Any) -> Runnable:
    """
    Returns a Runnable mapping {features, modules, interfaces, decisions} -> RAPlanDraft.

    For Anthropic (Claude) we use the new JSON-schema structured outputs.
    For OpenAI we fall back to function-calling structured outputs to avoid
    the stricter `response_format` schema validation.
    """
    use_function_calling = False

    # Detect ChatOpenAI safely (ChatOpenAI may be None if import failed)
    if ChatOpenAI is not None:
        try:
            if isinstance(llm, ChatOpenAI):
                use_function_calling = True
        except Exception:
            # If type checking fails for any reason, just fall back to json_schema
            use_function_calling = False

    if use_function_calling:
        structured_llm = llm.with_structured_output(
            RAPlanDraft,
            method="function_calling",
        )
    else:
        structured_llm = llm.with_structured_output(
            RAPlanDraft,
            method="json_schema",
            strict=True,
        )

    defaults: Dict[str, Any] = {
        "max_epics": 10,
        "max_stories_total": 200,
        "max_stories_per_epic": 20,
    }
    if knobs:
        defaults.update(knobs)
    defaults.setdefault("exemplar", "")

    prompt = ChatPromptTemplate.from_messages([
        ("system", _SYS),
        ("human", _HUMAN),
    ]).partial(**defaults)

    return prompt | structured_llm

_SYS_MINIMAL = """You are a Requirements Analyst on an Agile Software Delivery team.
Goal: produce **MVP-sized** Epics and Stories that a single coding agent can implement iteratively.

Principles
• Shippable epics: each epic should be a demoable increment (for example, an initial scaffold or a complete feature slice).
• No scope creep: work within the scope implied by the product vision and features.
• Keep it concise: one sentence per description; verb-first titles.
• Avoid proliferation: choose the fewest epics and stories that still cover the requested behaviour.
• Execution economics: avoid 'spike/research/tooling/refactor' stories unless explicitly required by the vision.

Output contract
• Produce a small set of epics that together cover the product vision.
• For each epic, provide: title, description, priority_rank (int, 1..K), depends_on (list of epic titles in this draft; [] if none).
• For each story, provide: epic_title, title, description, priority_rank (int, 1..K within that epic), depends_on (list of story titles in the same epic; [] if none).
• Priority ranks must be integers starting at 1 and gap-free for epics, and separately gap-free within each epic’s stories.
• Dependencies must reference existing titles and must point only to items that come earlier in rank.

EXEMPLAR / FEEDBACK HINTS (optional):
• The exemplar may contain prior feedback (e.g., critiques, anti-patterns).
• Use it as guidance on what to improve/avoid (scope control, bloat, ordering, dependency correctness).
• Do NOT copy exemplar content. Do NOT quote or repeat any feedback text in your output.

--- EXEMPLAR START ---
{exemplar}
--- EXEMPLAR END ---
"""

_HUMAN_MINIMAL = """Context
Vision Features: {features}
Proposed Solution — Modules: {modules}
Proposed Solution — Interfaces: {interfaces}
Proposed Solution — Decisions: {decisions}

Guidance
• Use the vision features as your primary source of truth.
• Group related behaviour into epics that feel like coherent, demoable slices of value.
• Within each epic, define a small set of clear user stories focused on observable behaviour and outcomes.
• Prefer fewer, more complete stories (vertical slices) over many micro-stories.
Return JSON ONLY that matches the RAPlanDraft schema.
"""

def make_minimal_chain(llm: Any, **knobs: Any) -> Runnable:
    """
    Returns a Runnable that uses a lighter-weight RA prompt (minimal context engineering),
    while keeping the same output structure (RAPlanDraft).
    """
    use_function_calling = False
    if ChatOpenAI is not None:
        try:
            if isinstance(llm, ChatOpenAI):
                use_function_calling = True
        except Exception:
            use_function_calling = False

    if use_function_calling:
        structured_llm = llm.with_structured_output(
            RAPlanDraft,
            method="function_calling",
        )
    else:
        structured_llm = llm.with_structured_output(
            RAPlanDraft,
            method="json_schema",
            strict=True,
        )

    defaults: Dict[str, Any] = {
        "max_epics": 10,
        "max_stories_total": 200,
        "max_stories_per_epic": 20,
    }
    if knobs:
        defaults.update(knobs)
    defaults.setdefault("exemplar", "")

    prompt = ChatPromptTemplate.from_messages([
        ("system", _SYS_MINIMAL),
        ("human", _HUMAN_MINIMAL),
    ]).partial(**defaults)

    return prompt | structured_llm