from __future__ import annotations
from typing import Any, Dict, List, Optional, Sequence, Union, cast, AsyncIterator, Protocol, runtime_checkable
from fastapi import Request

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langgraph.graph.message import add_messages, AnyMessage
from langchain_core.tools import BaseTool
from langchain_core.language_models.chat_models import BaseChatModel
from app.configs.settings import get_settings
from app.agents.coding.serena_tools import get_serena_tools, close_serena
from app.agents.lc.model_factory import make_chat_model  # your existing factory

from collections import deque
import json
import asyncio

@runtime_checkable
class _SupportsAStreamEvents(Protocol):
    # Accept whatever the underlying runner yields (e.g., StreamEvent).
    def astream_events(self, *args, **kwargs) -> AsyncIterator[Any]:
        ...

@runtime_checkable
class _SupportsAInvoke(Protocol):
    async def ainvoke(self, *args, **kwargs) -> Any:
        ...

class _AgentRunnable(_SupportsAStreamEvents, _SupportsAInvoke, Protocol):
    pass

FALLBACK_NO_SHELL = (
    "Shell may be unavailable. If you cannot run commands, scaffold by writing files directly:\n"
    "- create package.json with minimal scripts (dev, build, start)\n"
    "- tsconfig.json, vite.config.ts, src/main.tsx, src/App.tsx\n"
    "- server/index.ts with Express app\n"
    "Use create_text_file / insert_* / replace_* tools to implement.\n"
)

SYSTEM_PROMPT = """You are CLAIRE's Coding Agent (Serena).
Use ONLY the provided Serena tools for code actions (read/edit/patch/move; small allowed commands).

STRICT EDITING PLAYBOOK (follow in order):
1) Locate target:
   - Always call get_symbols_overview(relative_path=...) on the file you intend to change.
   - Then call find_symbol(name_path=..., relative_path=..., include_body=True) to get the exact target.
   - If find_symbol returns 0 matches, do NOT guess: first try search_for_pattern to pinpoint location.

2) Normalize name_path (IMPORTANT — never include a file path in name_path):
   - TypeScript/JavaScript:
     • Top-level function: "functionName"
     • Class method: "ClassName.methodName"
     • React component function: "ComponentName"
     • For exports like `export const foo = () => {}`: use "foo"
   - Python (if present): "ClassName/__init__", "ClassName/method", or "function_name"
   - Only pass the file path via relative_path=<path from project root>.

3) Edit safely:
   - When you found the symbol: use replace_symbol_body(name_path, relative_path, new_body).
   - When you did NOT find a symbol but know where code belongs:
       • If the file has symbols, use insert_before_symbol or insert_after_symbol against a real symbol name from get_symbols_overview.
       • If the file has no symbols or you simply need to add code at the end, use append_to_file(relative_path, content).
   - When adjusting small snippets, prefer replace_regex scoped by unique anchors.

4) Verify:
   - After every change, re-read only the affected file/symbols (get_symbols_overview/find_symbol with include_body=True) to confirm.

GENERAL RULES:
- Work in the FEWEST steps needed for the current task or story.
- When given a Story plus a list of Tasks, implement all of the tasks for that single story in one coherent sweep, respecting any depends_on and priority fields.
- Do NOT implement tasks from other stories or epics unless explicitly instructed.
- Stay strictly within the task or story scope; skip tests and broad refactors unless asked.
- Prefer structured edits (symbol-level / patch) over large rewrites.
- Keep diffs minimal and idempotent.
"""


JsonMessage = Dict[str, Any]
MessagesInput = List[Union[AnyMessage, JsonMessage]]

# --- Simple async retry helper for transient LLM failures (HTTP 500, timeouts, etc.) ---
async def _sleep_backoff(attempt: int, base: float) -> None:
    # exponential: base, 2*base, 4*base, ...
    await asyncio.sleep(base * (2 ** attempt))

def _tool_signature(ev: dict) -> str:
    """
    Build a short, stable signature for a tool call from LC event dicts.
    Works for on_tool_start / on_tool_end; ignores LLM/chain events.
    """
    event_type = ev.get("event") or ev.get("type")
    if event_type not in ("on_tool_start", "on_tool_end"):
        return ""

    # Try to pull a tool name and its input/args in a robust way
    name = ev.get("name") or ev.get("tool_name") or ""
    data = ev.get("data") or {}
    # 'input' is typical on on_tool_start; 'output' on end; fall back to kwargs-like dicts
    payload = data.get("input") or data.get("output") or data.get("kwargs") or data.get("tool_input") or {}
    try:
        s = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    except Exception:
        s = str(payload)

    # Keep signature small and stable
    return f"{event_type}:{name}:{s}"

class CodingAgent:
    def __init__(
        self,
        model: Optional[str] = None,
        temperature: float = 0.0,
        *,
        provider: Optional[str] = None,
    ):
        # keep a handle to settings for later (recursion_limit, etc.)
        self.settings = get_settings()
        # use your factory, which already returns a BaseChatModel with retries/timeouts set
        self.llm: BaseChatModel = make_chat_model(
            model=model,
            temperature=temperature,
            provider=provider,
        )
        # NOTE: avoid .bind(...) here because it returns a Runnable (breaks create_agent typing)

    async def astream_events(self, state: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> AsyncIterator[Dict[str, Any]]:
        runnable: Optional[_SupportsAStreamEvents] = None
        # Try common attribute names you may be using to store the graph/runnable
        for attr in ("graph", "_graph", "agent", "_agent", "runnable", "_runnable"):
            candidate = getattr(self, attr, None)
            if candidate is not None and hasattr(candidate, "astream_events"):
                runnable = cast(_SupportsAStreamEvents, candidate)
                break

        if runnable is None:
            # As a last resort, emit a terminal event so callers don't crash.
            yield {"event": "on_chain_end", "name": "agent", "data": {"result": {"messages": []}}}
            return

        # Normal streaming path
        async for ev in runnable.astream_events(state, config=config or {}):
            if isinstance(ev, dict):
                yield ev
            else:
                # Best-effort coercion for TypedDict/dataclass-like events
                try:
                    yield dict(ev)  # Mapping or TypedDict
                except Exception:
                    try:
                        yield ev.__dict__  # dataclass / object with __dict__
                    except Exception:
                        yield {"event": "unknown", "data": str(ev)}

    async def _agent_for(self, request: Request, project_dir: Optional[str]) -> _AgentRunnable:
        tools = await get_serena_tools(request, project_dir=project_dir)

        # --- Language-server warm-up: give TS server a moment to finish initializing ---
        warm = float(getattr(self.settings, "SERENA_LS_READY_WARMUP_SECS", 1.2))
        if warm > 0:
            await asyncio.sleep(warm)

        tools_seq: Sequence[BaseTool] = cast(Sequence[BaseTool], tools)
        agent = create_agent(
            model=cast(BaseChatModel, self.llm),
            tools=tools_seq,
            system_prompt=SYSTEM_PROMPT + "\n\n" + FALLBACK_NO_SHELL,
            name="SerenaCoder",
        )
        return agent

    async def implement_story(
        self,
        request: Request,
        *,
        project_dir: str,
        product_vision: str,
        technical_solution: str,
        epic_title: str,
        story_title: str,
        story_desc: str,
        story_tasks: List[str],
    ) -> dict:
        """
        Execute the FEWEST Serena steps to complete ALL tasks for a single story
        with full PV/TS/story context.

        The story_tasks list should contain human-readable task titles (strings).
        Returns {output, events}.
        """

        agent: _AgentRunnable = await self._agent_for(request, project_dir=project_dir)

        tasks_json = json.dumps(story_tasks, indent=2, ensure_ascii=False)

        prompt = (
            f"Product Vision (summary): {product_vision}\n"
            f"Technical Solution (stack/modules): {technical_solution}\n"
            f"Epic: {epic_title}\n"
            f"Story: {story_title} — {story_desc}\n"
            f"Story Tasks (with dependencies and priority):\n{tasks_json}\n\n"
            "Implement ALL of these tasks for this story in the fewest possible steps using Serena tools.\n"
            "Respect depends_on and priority_rank when choosing the order of implementation.\n"
            "Do NOT implement tasks from other stories or epics."
        )

        # LangGraph-compatible input (messages in state)
        state = {"messages": [HumanMessage(content=prompt)]}

        # Bound tool/LLM recursion (iterations)
        cfg = {"recursion_limit": int(getattr(self.settings, "CODING_RECURSION_LIMIT", 30))}

        events: List[Dict[str, Any]] = []

        # ---- loop-guard state (simple, local, stateless across calls) ----
        guard_enabled = bool(getattr(self.settings, "CODING_LOOP_GUARD_ENABLED", True))
        win = int(getattr(self.settings, "CODING_LOOP_WINDOW", 6))
        max_same = int(getattr(self.settings, "CODING_LOOP_MAX_SAME", 3))
        recent = deque(maxlen=win)
        aborted_reason: Optional[str] = None

        try:
            # --- LLM stream retries (wrap entire stream) ---
            max_retries = int(getattr(self.settings, "CODING_LLM_RETRIES", 2))
            retry_base = float(getattr(self.settings, "CODING_LLM_RETRY_BASE_SECS", 1.5))

            for attempt in range(max_retries + 1):
                try:
                    async for ev in agent.astream_events(cast(Any, state), config=cfg):
                        ev = cast(Dict[str, Any], ev)
                        events.append(ev)

                        if guard_enabled:
                            sig = _tool_signature(ev)
                            if sig:
                                recent.append(sig)
                                if len(recent) >= max_same and len(set(recent)) == 1:
                                    aborted_reason = (
                                        f"Aborting due to loop guard: repeated identical tool call "
                                        f"'{recent[0]}' {len(recent)}× without progress."
                                    )
                                    break
                    # if we finished the stream without error, break retry loop
                    break
                except Exception as e:
                    if attempt >= max_retries:
                        raise
                    # annotate and back off, then retry the whole stream
                    events.append(
                        {
                            "event": "warning",
                            "message": f"LLM stream error (attempt {attempt+1}/{max_retries+1}): {e}. Retrying...",
                        }
                    )
                    await _sleep_backoff(attempt, retry_base)

            # If we aborted mid-stream, return early with a clear message
            if aborted_reason:
                return {"output": aborted_reason, "events": events}

            # --- Final LLM call retries (for last response assembly) ---
            final = None
            for attempt in range(max_retries + 1):
                try:
                    final = await agent.ainvoke(cast(Any, state), config=cfg)
                    break
                except Exception as e:
                    if attempt >= max_retries:
                        raise
                    events.append(
                        {
                            "event": "warning",
                            "message": f"LLM final invoke error (attempt {attempt+1}/{max_retries+1}): {e}. Retrying...",
                        }
                    )
                    await _sleep_backoff(attempt, retry_base)

            # Extract final assistant text (unchanged)
            output_text: str = ""
            msgs = final.get("messages") if isinstance(final, dict) else None
            if isinstance(msgs, list) and msgs:
                for m in reversed(msgs):
                    if getattr(m, "type", None) == "ai" or m.__class__.__name__ == "AIMessage":
                        output_text = getattr(m, "content", "") or ""
                        break
            if not output_text:
                output_text = str(final)

            return {"output": output_text, "events": events}
        finally:
            await close_serena(request)

    async def implement_task(
        self,
        request: Request,
        *,
        project_dir: str,
        product_vision: str,
        technical_solution: str,
        epic_title: str,
        story_title: str,
        story_desc: str,
        task_title: str,
    ) -> dict:
        """
        Backwards-compatible wrapper that treats a single task as a one-task story.
        Prefer calling implement_story with the full story_tasks list when possible.
        """
        # Single-task story: just pass the title as a one-element list of strings
        story_tasks: List[str] = [task_title]

        return await self.implement_story(
            request,
            project_dir=project_dir,
            product_vision=product_vision,
            technical_solution=technical_solution,
            epic_title=epic_title,
            story_title=story_title,
            story_desc=story_desc,
            story_tasks=story_tasks,
        )


