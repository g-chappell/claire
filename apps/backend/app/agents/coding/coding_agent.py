# apps/backend/app/agents/coding/coding_agent.py
from __future__ import annotations
from typing import Optional, Sequence, cast, Any, List, Dict, Annotated, TypedDict, Union
from fastapi import Request

from langchain.chat_models import init_chat_model
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.tools import BaseTool
from langgraph.graph.message import add_messages, AnyMessage

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

# Allow both LC message objects and dict-like messages (what the v1 stubs accept)
JsonMessage = Dict[str, Any]
MessagesInput = List[Union[AnyMessage, JsonMessage]]

class AgentInputState(TypedDict):
    # "messages" uses the add_messages reducer in LangGraph
    messages: Annotated[MessagesInput, add_messages]


class CodingAgent:
    def __init__(self, model: Optional[str] = None, temperature: float = 0.0):
        settings = get_settings()
        self.llm = init_chat_model(
            model=(model or settings.LLM_MODEL),
            model_provider="anthropic",
            temperature=temperature,
        )

    async def for_request(self, request: Request, project_dir: Optional[str] = None):
        tools = await get_serena_tools(request, project_dir=project_dir)
        if not tools:
            raise RuntimeError("Serena MCP connected but exposed 0 tools.")
        tools_seq: Sequence[BaseTool] = cast(Sequence[BaseTool], tools)

        # v1: returns a runnable graph directly (no .compile())
        agent = create_agent(
            model=self.llm,
            tools=tools_seq,
            system_prompt=SYSTEM_PROMPT,
            name="SerenaCoder",
        )
        return agent

    async def implement_story(
        self,
        request: Request,
        story_title: str,
        story_desc: str,
        project_dir: Optional[str] = None,
    ) -> dict:
        agent = await self.for_request(request, project_dir=project_dir)

        messages: MessagesInput = [
            HumanMessage(
                content=(
                    f"Story: {story_title}\n\n"
                    f"Acceptance (or description):\n{story_desc}\n\n"
                    "Implement this story using Serena tools, step by step."
                )
            )
        ]

        # ✔ Type the event list correctly
        intermediate_events: List[Dict[str, Any]] = []

        # ✔ Provide a properly-typed state for the agent
        state: AgentInputState = {"messages": messages}

        try:
            # Stream events (tool calls, model tokens, etc.)
            async for ev in agent.astream_events(cast(Any, state)):
                intermediate_events.append(cast(Dict[str, Any], ev))

            # Final result
            final = await agent.ainvoke(cast(Any, state))

            # Extract a useful output string
            output_text: Optional[str] = None
            msgs = final.get("messages") if isinstance(final, dict) else None
            if isinstance(msgs, list) and msgs:
                for m in reversed(msgs):
                    if getattr(m, "type", None) == "ai" or m.__class__.__name__ == "AIMessage":
                        output_text = getattr(m, "content", None)
                        break
            if output_text is None:
                output_text = str(final)

            return {
                    "output": output_text,
                    "intermediate_steps": intermediate_events,  # List[StreamEvent]
                }
        finally:
            await close_serena(request)
