# apps/backend/app/agents/coding/serena_tools.py
from __future__ import annotations

import os
import asyncio
from typing import Any, Dict, Optional, cast
from fastapi import Request

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_core.tools import StructuredTool, BaseTool
from pydantic import BaseModel, Field

# MCP exceptions
from mcp.shared.exceptions import McpError
try:
    # Newer MCP exports this; use when available
    from mcp.client.stdio import EndOfStream  # type: ignore
except Exception:
    # Fallback for older MCP builds
    class EndOfStream(Exception):
        ...

from app.configs.settings import get_settings


def _default_serena_args() -> list[str]:
    """
    Default args for start-mcp-server. We run:
        start-mcp-server serena --project <dir> [--context <ctx>]
    """
    return ["serena"]


async def get_serena_tools(request: Request, project_dir: Optional[str] = None):
    """
    Start a Serena MCP server (stdio by default) scoped to `project_dir`
    and return its tools as LangChain tools.
    """
    settings = get_settings()

    # Resolve workspace path (your per-run repo)
    project = os.path.abspath(project_dir or settings.SERENA_PROJECT_DIR)

    # Build the Serena command
    command = getattr(settings, "SERENA_COMMAND", "start-mcp-server")
    args = getattr(settings, "SERENA_ARGS", None) or _default_serena_args()

    # Use an existing Serena context that exposes read/write tools.
    # "agent" is widely available; "ide-assistant" is another option.
    ctx = (getattr(settings, "SERENA_CONTEXT", None) or os.getenv("SERENA_CONTEXT", "agent")).strip()

    cmd = [command, *args, "--project", project]
    if ctx:
        cmd += ["--context", ctx]

    # Choose transport
    transport = (getattr(settings, "SERENA_TRANSPORT", None) or "stdio").strip().lower()

    servers: Dict[str, Dict[str, Any]] = {}
    if transport == "stdio":
        # Spawn Serena as a child process
        servers["serena"] = {
            "transport": "stdio",
            "command": cmd[0],
            "args": cmd[1:],
        }
    elif transport == "streamable_http":
        servers["serena"] = {
            "transport": "streamable_http",
            "url": "http://127.0.0.1:9121/mcp",
        }
    else:  # "sse" or anything else -> default SSE URL
        servers["serena"] = {
            "transport": "sse",
            "url": "http://127.0.0.1:9121/mcp",
        }

    client = MultiServerMCPClient(connections=cast("dict[str, Any]", servers))

    # Persist the session for the duration of the request so LangChain tools
    # keep a live transport. We'll close it in a companion helper.
    last_err: Exception | None = None
    for attempt in range(5):
        try:
            cm = client.session("serena")
            session = await cm.__aenter__()  # <- DO NOT close here
            # store an aexit closer on the request to clean up later
            closers = getattr(request.state, "_serena_close", None)
            if closers is None:
                closers = []
                request.state._serena_close = closers
            closers.append(cm.__aexit__)

            tools = await load_mcp_tools(session)

            # --- Patch: make create_text_file tolerant of missing `content` ---
            orig_create = next((t for t in tools if t.name == "create_text_file"), None)
            if orig_create:
                # drop the original from the exposed toolset
                tools = [t for t in tools if t.name != "create_text_file"]
                orig_create_tool: BaseTool = cast(BaseTool, orig_create)

                class _CreateArgs(BaseModel):
                    relative_path: str = Field(..., description="Path relative to the project root.")
                    content: Optional[str] = Field(
                        None,
                        description="File contents. If omitted, a minimal stub will be written."
                    )

                def _stub_for(path: str) -> str:
                    p = path.lower()
                    base = os.path.splitext(os.path.basename(path))[0]
                    ident = "".join(part.title() for part in base.replace("-", " ").replace("_", " ").split())
                    if p.endswith(".ts"):
                        return f"/** Auto-stub created by CLAIRE */\nexport class {ident} {{}}\n"
                    if p.endswith(".tsx"):
                        return f"/** Auto-stub created by CLAIRE */\nexport default function {ident}() {{\n  return null;\n}}\n"
                    if p.endswith(".js"):
                        return "// Auto-stub created by CLAIRE\n"
                    if p.endswith(".md"):
                        return f"# {ident}\n"
                    return "\n"  # ensure non-empty string

                async def _create_text_file_safe(relative_path: str, content: Optional[str] = None):
                    payload = {
                        "relative_path": relative_path,
                        "content": (content if content and content.strip() != "" else _stub_for(relative_path)),
                    }
                    # Prefer new-style .ainvoke (LC 0.2+); fall back to .arun if needed.
                    ainvoke = getattr(orig_create_tool, "ainvoke", None)
                    if ainvoke is not None:
                        return await ainvoke(payload)  # type: ignore[misc]
                    return await orig_create_tool.arun(payload)  # type: ignore[attr-defined]

                tools.append(
                    StructuredTool.from_function(
                        name="create_text_file",
                        description="Create a new text file. If 'content' is omitted, writes a minimal, valid stub.",
                        coroutine=_create_text_file_safe,
                        args_schema=_CreateArgs,
                    )
                )
            # --- End patch ---    

            if tools:
                return tools
            last_err = RuntimeError("Serena session opened but returned 0 tools")
        except (McpError, EndOfStream, ConnectionError, RuntimeError) as e:
            last_err = e
            # brief backoff
            await asyncio.sleep(0.8 * (attempt + 1))

    raise RuntimeError(
        "Serena MCP connection failed or exposed no tools. "
        f"cmd={' '.join(cmd)} | project={project} | context={ctx} | transport={transport}. "
        f"Last error: {last_err}"
    )

async def close_serena(request: Request) -> None:
    """Close any open Serena MCP sessions registered on this request."""
    closers = getattr(request.state, "_serena_close", [])
    while closers:
        closer = closers.pop()
        try:
            await closer(None, None, None)
        except Exception:
            pass