from __future__ import annotations
import logging
from typing import Any, List

from langchain_core.callbacks import BaseCallbackHandler

logger = logging.getLogger(__name__)

def _preview(s: str, n: int = 4000) -> str:
    s = (s or "")
    return s if len(s) <= n else (s[:n] + "\n...[TRUNCATED]...\n" + s[-800:])

class PromptDebugHandler(BaseCallbackHandler):
    """Logs the final messages passed into the chat model."""

    def on_chat_model_start(self, serialized: Any, messages: List[List[Any]], **kwargs: Any) -> None:
        meta = kwargs.get("metadata") or {}
        run_id = meta.get("run_id", "")
        agent = meta.get("agent", "")
        phase = meta.get("phase", "")

        # LangChain passes messages as List[List[BaseMessage]]
        try:
            batch = messages[0] if messages else []
        except Exception:
            batch = []

        logger.info("LLM_PROMPT_FINAL run=%s phase=%s agent=%s n_msgs=%d", run_id, phase, agent, len(batch))

        for i, m in enumerate(batch):
            role = getattr(m, "type", None) or getattr(m, "role", None) or m.__class__.__name__
            content = getattr(m, "content", None)
            if isinstance(content, list):
                # sometimes content is structured
                content = str(content)
            logger.info("LLM_MSG[%d] role=%s len=%d\n%s", i, role, len(content or ""), _preview(content or ""))
