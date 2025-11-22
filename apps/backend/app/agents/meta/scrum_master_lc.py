# apps/backend/app/agents/meta/scrum_master_lc.py
from __future__ import annotations
from typing import Literal, Optional, Tuple
from sqlalchemy.orm import Session
from app.agents.lc.model_factory import make_chat_model

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

    llm = make_chat_model()
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

    # Persist to DB on caller
    return ai_text, getattr(llm, "model_name", getattr(llm, "model", "unknown"))

