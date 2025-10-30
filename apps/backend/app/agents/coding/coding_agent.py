# apps/backend/app/agents/coding/coding_agent.py
from __future__ import annotations
from typing import Optional, Sequence, cast, Any
from fastapi import Request
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import BaseTool
from langchain_anthropic import ChatAnthropic  # you already use Anthropic
from app.configs.settings import get_settings
from app.agents.coding.serena_tools import get_serena_tools, close_serena

SYSTEM_PROMPT = """You are CLAIRE's Coding Agent.
Use Serena MCP tools for ALL code understanding and edits:
- find_symbol, find_referencing_symbols, read_file, create_text_file,
  insert_after_symbol, replace_symbol, move_symbol, run_tests, etc.
Rules:
- Work in small, verifiable steps per story.
- After each edit, read relevant files/symbols to verify changes.
- Prefer symbol-level edits over raw string replaces.
- Do not hallucinate paths; list files before writing.
- Keep diffs minimal and idempotent; re-run tests when available.
"""

class CodingAgent:
    def __init__(self, model: Optional[str] = None, temperature: float = 0.0):
        settings = get_settings()
        Anthropic = cast(Any, ChatAnthropic)
        try:
            # Older sig: model_name + (timeout, stop) expected by the stub
            self.llm = Anthropic(
                model_name=(model or settings.LLM_MODEL),
                temperature=temperature,
                timeout=None,
                stop=None,
            )
        except TypeError:
            # Newer sig: model=... (timeout/stop optional)
            self.llm = Anthropic(
                model=(model or settings.LLM_MODEL),
                temperature=temperature,
            )

    async def for_request(self, request: Request, project_dir: Optional[str] = None):
        tools = await get_serena_tools(request, project_dir=project_dir)
        if not tools:
            raise RuntimeError("Serena MCP connected but exposed 0 tools.")
        tools_seq: Sequence[BaseTool] = cast(Sequence[BaseTool], tools)

        # Build a proper prompt template
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", SYSTEM_PROMPT),
                MessagesPlaceholder("messages"),          # your user/task content
                MessagesPlaceholder("agent_scratchpad"),  # required by LC agent
            ]
        )

        agent = create_tool_calling_agent(self.llm, tools_seq, prompt=prompt)
        executor = AgentExecutor(
            agent=agent,
            tools=tools_seq,
            verbose=True,
            return_intermediate_steps=True,
            handle_parsing_errors=True,
        )
        return executor

    async def implement_story(self, request: Request, story_title: str, story_desc: str, project_dir: Optional[str] = None) -> dict:
        executor = await self.for_request(request, project_dir=project_dir)
        # SYSTEM_PROMPT is in the prompt; send the user task as `messages`
        messages = [
            HumanMessage(
                content=(
                    f"Story: {story_title}\n\n"
                    f"Acceptance (or description):\n{story_desc}\n\n"
                    "Implement this story using Serena tools, step by step."
                )
            )
        ]
        try:
            res = await executor.ainvoke({"messages": messages})
            return {
                "output": res.get("output"),
                "intermediate_steps": res.get("intermediate_steps", []),
            }
        finally:
            # ensure the stdio/SSE transport is torn down even on errors
            await close_serena(request)
