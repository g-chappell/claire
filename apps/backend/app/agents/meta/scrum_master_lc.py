# apps/backend/app/agents/meta/scrum_master_lc.py
from __future__ import annotations
from typing import Literal, Optional, Tuple
from sqlalchemy.orm import Session
import time

from app.configs.settings import get_settings
from app.storage.models import RunManifestORM
from app.agents.lc.model_factory import make_chat_model
from app.core.metrics import log_llm_call

# Artefact kinds we support
Kind = Literal["epic", "story", "task"]

SYSTEM_PROMPT = """You are a Scrum Master AI. Your job:
- Read the human feedback and the artefact context.
- Synthesize a concise AI feedback (max 300 words).
- Do NOT prescribe file paths or code tools.
- Focus on clarity, risks, sequencing, testability, and acceptance signals.
- If the human feedback is vague, call that out and suggest how to sharpen it.
Output ONLY the AI feedback paragraph/plain text.
"""

def _context_from_orm(kind: Kind, obj: object) -> str:
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
    kind: Kind,
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

    # Build a single text blob for metrics (system + user)
    full_prompt = (
        f"[SYSTEM]\n{SYSTEM_PROMPT}\n\n"
        f"[USER]\n{prompt_user}"
    )

    start_time = time.time()
    ai_text: str = ""

    try:
        msg = llm.invoke([
            {"role": "system", "content": SYSTEM_PROMPT},
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
