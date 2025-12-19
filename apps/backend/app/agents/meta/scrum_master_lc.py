# apps/backend/app/agents/meta/scrum_master_lc.py
from __future__ import annotations
from typing import Literal, Optional, Tuple
from sqlalchemy.orm import Session
import time

from app.configs.settings import get_settings
from app.storage.models import RunManifestORM
from app.agents.lc.model_factory import make_chat_model
from app.core.metrics import log_llm_call

ORMKind = Literal["epic", "story", "task"]

PlanKind = Literal[
    "product_vision",
    "technical_solution",
    "ra_plan",
    "story_tasks",
    "epic",
    "story",
    "task",
]

BASE_SYSTEM_PROMPT = """You are a Scrum Master AI.

Purpose:
Your feedback will be used as INPUT to the next planning run. Write reusable guidance that improves the *next version* of the artefact (clarity, completeness, ordering, testability, and cost-control).

Generalization requirement (critical):
- Your output will be stored as reusable prompt memory.
- Do NOT mention internal IDs, exact filenames/paths, or exact module/class names.
- Do NOT quote or restate the artefact text verbatim.
- Convert observations into reusable rules, patterns, and constraints that apply to similar artefacts.
- Stay domain-aware but write guidance as general planning/architecture/task-quality rules.

Hard rules:
- Output ONLY 1–5 bullet points. No headings. No paragraphs.
- Each bullet must be an instruction/constraint for future planning (start with Ensure/Require/Avoid/Include/Prefer).
- Use clear, concise language suitable for software engineers and product managers.
"""

KIND_SYSTEM_APPENDIX = {
  # ---- Stage gate artefacts ----
  "product_vision": """Artefact: Product Vision
Focus on:
- Keep advice generalizable; do not name IDs/paths/module names.
- Clear user + problem + value proposition (who/what/why).
- In-scope vs out-of-scope boundaries.
- Success metrics (measurable), assumptions, constraints, and non-functionals.
- UX expectations at a high level (key screens/flows) without implementation detail.
- Remove marketing fluff; replace with testable statements.""",

  "technical_solution": """Artefact: Technical Solution
Focus on:
- Keep advice generalizable; do not name IDs/paths/module names.
- Architecture coherence (major components and responsibilities).
- Data model / key entities and state ownership.
- API boundaries/contracts (what talks to what, and what returns what).
- Error handling, security basics, and performance constraints.
- Testing strategy at a system level (unit/integration/e2e), and acceptance alignment.
- Identify risky dependencies or unclear integration points.""",

  "ra_plan": """Artefact: RA Plan (Epics & Stories)
Focus on:
- Keep advice generalizable; do not name IDs/paths/module names.
- Correct sequencing: scaffold/foundations first, features later.
- Dependencies: identify missing depends_on, ordering conflicts, and parallelizable work.
- Right-sizing: epics should be deliverable; stories should be independently valuable.
- Remove duplicates and “nice-to-have” scope from MVP.
- Ensure every story maps back to PV/TS and has a clear outcome (not just activity).""",

  "story_tasks": """Artefact: Story Tasks (per-story)
Focus on:
- Keep advice generalizable; do not name IDs/paths/module names.
- Task granularity: tasks should be small, sequential, and implementable.
- Avoid bloat: remove over-engineering and excessive steps/tools.
- Make DoD explicit and checkable (UI behaviour, API responses, validations, edge cases).
- Ensure tasks cover wiring + state + UX feedback + error/empty states (as relevant).
- Flag missing prerequisites (scaffold, types, endpoints) as dependencies, not new scope.""",

  # ---- Legacy artefacts ----
  "epic": """Artefact: Epic
Focus on: epic scope boundaries, value/outcome, sequencing/dependencies, and risk.""",
  "story": """Artefact: Story
Focus on: clarity, acceptance signals, edge cases, and dependency ordering.""",
  "task": """Artefact: Task
Focus on: single responsibility, concrete DoD, and removing unnecessary steps.""",
}

def _system_prompt_for(kind: PlanKind) -> str:
    appendix = KIND_SYSTEM_APPENDIX.get(kind, "").strip()
    return BASE_SYSTEM_PROMPT if not appendix else (BASE_SYSTEM_PROMPT + "\n\n" + appendix)

def _context_from_orm(kind: ORMKind, obj: object) -> str:
    # Extract minimal, safe context for each artefact kind
    if kind == "epic":
        title = getattr(obj, "title", "")
        desc = getattr(obj, "description", "") or ""
        return f"EPIC\nTitle: {title}\nDescription:\n{desc}"
    if kind == "story":
        title = getattr(obj, "title", "")
        desc = getattr(obj, "description", "") or ""
        tests = getattr(obj, "tests", []) or []
        tests_str = "\n".join(f"- {t}" for t in tests)
        return f"STORY\nTitle: {title}\nDescription:\n{desc}\nTests:\n{tests_str}"
    # task
    title = getattr(obj, "title", "")
    dod = getattr(obj, "definition_of_done", []) or []
    dod_str = "\n".join(f"- {d}" for d in dod)
    return f"TASK\nTitle: {title}\nDefinition of Done:\n{dod_str}"

def generate_ai_feedback(
    db: Session,
    *,
    run_id: str,
    kind: ORMKind,
    artefact_id: str,
    human_feedback: Optional[str],
) -> Tuple[str, str]:
    """
    Returns (ai_feedback, used_model)

    Now instrumented with metrics:
    - phase: "retrospective"
    - agent: "scrum_master"
    - run_id: this run
    - story_id: artefact_id if kind == "story" else None
    - metadata: {"kind": kind, "artefact_id": artefact_id}
    """
    from app.storage.models import EpicORM, StoryORM, TaskORM

    if kind == "epic":
        obj = db.get(EpicORM, artefact_id)
    elif kind == "story":
        obj = db.get(StoryORM, artefact_id)
    else:
        obj = db.get(TaskORM, artefact_id)

    if not obj or getattr(obj, "run_id", None) != run_id:
        raise ValueError("Artefact not found for this run")

    context_block = _context_from_orm(kind, obj)
    human_block = (human_feedback or getattr(obj, "feedback_human", "") or "").strip()
    prompt_user = (
        f"{context_block}\n\n"
        f"HUMAN FEEDBACK:\n{human_block if human_block else '(none provided)'}\n\n"
        "Write the AI feedback now."
    )

    # --- Resolve provider/model/temperature from RunManifest snapshot ---
    settings = get_settings()
    mf: Optional[RunManifestORM] = (
        db.query(RunManifestORM).filter_by(run_id=run_id).first()
    )
    data = (mf.data or {}) if mf and getattr(mf, "data", None) else {}

    raw_provider = (
        data.get("provider")
        or getattr(settings, "LLM_PROVIDER", None)
        or ""
    )
    provider = raw_provider.strip().lower() or None

    model = data.get("model") or getattr(settings, "LLM_MODEL", None)

    temp_val = data.get("temperature", None)
    try:
        temperature = float(
            temp_val if temp_val is not None else getattr(settings, "TEMPERATURE", 0.2)
        )
    except Exception:
        temperature = float(getattr(settings, "TEMPERATURE", 0.2))

    llm = make_chat_model(model=model, temperature=temperature, provider=provider)
    used_model = getattr(llm, "model_name", getattr(llm, "model", "unknown"))

    # Choose prompt variant for this artefact kind
    system_prompt = _system_prompt_for(kind)

    # Build a single text blob for metrics (system + user)
    full_prompt = (
        f"[SYSTEM]\n{system_prompt}\n\n"
        f"[USER]\n{prompt_user}"
    )

    start_time = time.time()
    ai_text: str = ""

    try:
        msg = llm.invoke([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt_user},
        ])

        def _to_text(content) -> str:
            # Normalize Anthropic/OpenAI-style message content into a plain string.
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = []
                for part in content:
                    if isinstance(part, dict):
                        # Anthropic/OpenAI SDKs often expose {"type": "text", "text": "..."} or similar
                        parts.append(str(part.get("text") or part.get("content") or ""))
                    else:
                        # Fallback for SDK-specific objects (e.g., content blocks)
                        text_attr = getattr(part, "text", None)
                        if text_attr is not None:
                            parts.append(str(text_attr))
                        else:
                            parts.append(str(part))
                return "".join(parts)
            # Final fallback
            try:
                return str(content)
            except Exception:
                return ""

        ai_text = _to_text(getattr(msg, "content", msg)).strip()
        end_time = time.time()

        # Metrics: successful Scrum Master feedback call
        try:
            log_llm_call(
                run_id=run_id,
                phase="retrospective",
                agent="scrum_master",
                provider=(provider or "unknown"),
                model=used_model,
                start_time=start_time,
                end_time=end_time,
                input_text=full_prompt,
                output_text=ai_text,
                story_id=artefact_id if kind == "story" else None,
                metadata={
                    "kind": kind,
                    "artefact_id": artefact_id,
                },
            )
        except Exception:
            # Metrics must never break normal behaviour
            pass

    except Exception as e:
        # Metrics for failed LLM call
        end_time = time.time()
        try:
            log_llm_call(
                run_id=run_id,
                phase="retrospective",
                agent="scrum_master",
                provider=(provider or "unknown"),
                model=used_model,
                start_time=start_time,
                end_time=end_time,
                input_text=full_prompt,
                output_text=f"ERROR: {e}",
                story_id=artefact_id if kind == "story" else None,
                metadata={
                    "kind": kind,
                    "artefact_id": artefact_id,
                    "error": str(e),
                },
            )
        except Exception:
            pass
        # Preserve the original behaviour (propagate error)
        raise

    # Persist to DB on caller
    return ai_text, used_model


def generate_ai_feedback_from_context(
    db: Session,
    *,
    run_id: str,
    kind: PlanKind,
    context_block: str,
    human_feedback: Optional[str],
    story_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> Tuple[str, str]:
    """
    Same Scrum Master behavior as generate_ai_feedback(), but for run-level or
    aggregated artefacts (e.g., ra_plan, story_tasks) that don't have a single ORM row.
    Returns (ai_feedback, used_model).
    """
    settings = get_settings()
    mf: Optional[RunManifestORM] = db.query(RunManifestORM).filter_by(run_id=run_id).first()
    data = (mf.data or {}) if mf and getattr(mf, "data", None) else {}

    raw_provider = (data.get("provider") or getattr(settings, "LLM_PROVIDER", None) or "")
    provider = raw_provider.strip().lower() or None
    model = data.get("model") or getattr(settings, "LLM_MODEL", None)

    temp_val = data.get("temperature", None)
    try:
        temperature = float(temp_val if temp_val is not None else getattr(settings, "TEMPERATURE", 0.2))
    except Exception:
        temperature = float(getattr(settings, "TEMPERATURE", 0.2))

    # Build the LLM (same pattern as generate_ai_feedback)
    llm = make_chat_model(model=model, temperature=temperature, provider=provider)
    used_model = getattr(llm, "model_name", getattr(llm, "model", "unknown"))

    # Choose prompt variant for this artefact kind (product_vision, technical_solution, ra_plan, story_tasks, etc.)
    system_prompt = _system_prompt_for(kind)

    human_block = (human_feedback or "").strip()
    prompt_user = (
        f"ARTEFACT_KIND: {kind}\n"
        f"{context_block.strip()}\n\n"
        f"HUMAN FEEDBACK:\n{human_block if human_block else '(none provided)'}\n\n"
        "Write the AI feedback now."
    )

    full_prompt = f"[SYSTEM]\n{system_prompt}\n\n[USER]\n{prompt_user}"

    start_time = time.time()
    ai_text: str = ""
    try:
        msg = llm.invoke([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt_user},
        ])

        # Reuse the normalizer from above
        content = getattr(msg, "content", msg)
        if isinstance(content, str):
            ai_text = content.strip()
        elif isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict):
                    parts.append(str(part.get("text") or part.get("content") or ""))
                else:
                    t = getattr(part, "text", None)
                    parts.append(str(t) if t is not None else str(part))
            ai_text = "".join(parts).strip()
        else:
            ai_text = str(content).strip()

        end_time = time.time()
        try:
            log_llm_call(
                run_id=run_id,
                phase="retrospective",
                agent="scrum_master",
                provider=(provider or "unknown"),
                model=used_model,
                start_time=start_time,
                end_time=end_time,
                input_text=full_prompt,
                output_text=ai_text,
                story_id=story_id,
                metadata={"kind": kind, **(metadata or {})},
            )
        except Exception:
            pass

    except Exception as e:
        end_time = time.time()
        try:
            log_llm_call(
                run_id=run_id,
                phase="retrospective",
                agent="scrum_master",
                provider=(provider or "unknown"),
                model=used_model,
                start_time=start_time,
                end_time=end_time,
                input_text=full_prompt,
                output_text=f"ERROR: {e}",
                story_id=story_id,
                metadata={"kind": kind, "error": str(e), **(metadata or {})},
            )
        except Exception:
            pass
        raise

    return ai_text, used_model
