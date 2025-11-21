from __future__ import annotations
from typing import Any, Dict, List, Optional, Sequence, Union, cast
from fastapi import Request

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langgraph.graph.message import add_messages, AnyMessage
from langchain_core.tools import BaseTool
from langchain_core.language_models.chat_models import BaseChatModel
from app.configs.settings import get_settings
from app.agents.coding.serena_tools import get_serena_tools, close_serena
from app.agents.lc.model_factory import make_chat_model  # your existing factory

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
- Work in the FEWEST steps needed for the current task.
- Stay strictly within the task's scope; skip tests and broad refactors unless asked.
- Prefer structured edits (symbol-level / patch) over large rewrites.
- Keep diffs minimal and idempotent.
"""

JsonMessage = Dict[str, Any]
MessagesInput = List[Union[AnyMessage, JsonMessage]]

class CodingAgent:
    def __init__(self, model: Optional[str] = None, temperature: float = 0.0):
            # keep a handle to settings for later (recursion_limit, etc.)
            self.settings = get_settings()
            # use your factory, which already returns a BaseChatModel with retries/timeouts set
            self.llm: BaseChatModel = make_chat_model(model=model, temperature=temperature)
            # NOTE: avoid .bind(...) here because it returns a Runnable (breaks create_agent typing)

    async def _agent_for(self, request: Request, project_dir: Optional[str]) -> Any:
        tools = await get_serena_tools(request, project_dir=project_dir)
        tools_seq: Sequence[BaseTool] = cast(Sequence[BaseTool], tools)
        agent = create_agent(
            model=cast(BaseChatModel, self.llm),
            tools=tools_seq,
            system_prompt=SYSTEM_PROMPT + "\n\n" + FALLBACK_NO_SHELL,
            name="SerenaCoder",
        )
        return agent

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
        Execute the FEWEST Serena steps to complete ONE task with full PV/TS/story context.
        Returns {output, events}.
        """
        agent = await self._agent_for(request, project_dir=project_dir)

        prompt = (
            f"Product Vision (summary): {product_vision}\n"
            f"Technical Solution (stack/modules): {technical_solution}\n"
            f"Epic: {epic_title}\n"
            f"Story: {story_title} — {story_desc}\n"
            f"Task: {task_title}\n\n"
            "Implement ONLY this task in the fewest possible steps using Serena tools."
        )

        # LangGraph-compatible input (messages in state)
        state = {"messages": [HumanMessage(content=prompt)]}

        # Bound tool/LLM recursion (iterations)
        cfg = {"recursion_limit": int(getattr(self.settings, "CODING_RECURSION_LIMIT", 30))}

        events: List[Dict[str, Any]] = []
        try:
            async for ev in agent.astream_events(cast(Any, state), config=cfg):
                events.append(cast(Dict[str, Any], ev))

            final = await agent.ainvoke(cast(Any, state), config=cfg)

            # Extract final assistant text
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
