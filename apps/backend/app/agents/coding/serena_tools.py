from __future__ import annotations
import os, asyncio
from typing import Any, Callable, Dict, List, Optional, cast
from fastapi import Request
from pydantic import BaseModel, Field

from langchain_core.tools import StructuredTool, BaseTool

# Your MCP client loader (names match common setups; keep as in your project)
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
# MCP exceptions
from mcp.shared.exceptions import McpError
try:
    from mcp.client.stdio import EndOfStream  # type: ignore
except Exception:
    class EndOfStream(Exception):
        ...


from app.configs.settings import get_settings

import shutil
import logging

logger = logging.getLogger(__name__)

def _resolve_executable(cmd0: str) -> str:
    """
    Return an absolute path to the executable or raise a friendly error.
    Works with absolute paths or PATH discovery. No shell.
    """
    if os.path.isabs(cmd0) and os.path.exists(cmd0) and os.access(cmd0, os.X_OK):
        return cmd0
    found = shutil.which(cmd0)
    if found:
        return found
    raise FileNotFoundError(
        f"SERENA_COMMAND '{cmd0}' not found on PATH. "
        "Install Serena or adjust SERENA_COMMAND/SERENA_ARGS. "
        "Examples:\n"
        "  SERENA_COMMAND=serena  SERENA_ARGS=['start-mcp-server']\n"
        "  SERENA_COMMAND=uvx     SERENA_ARGS=['--from','git+https://github.com/<org>/serena',"
        "'serena','start-mcp-server']\n"
        "Alternatively set SERENA_TRANSPORT=streamable_http and run the MCP server separately."
    )

async def get_serena_tools(request: Request, project_dir: Optional[str] = None) -> List[BaseTool]:
    """
    Start a Serena MCP session scoped to `project_dir` and return a FILTERED set of coding-only tools.
    """
    settings = get_settings()
    project = os.path.abspath(project_dir or settings.SERENA_PROJECT_DIR)

    command = getattr(settings, "SERENA_COMMAND", "start-mcp-server")
    args = getattr(settings, "SERENA_ARGS", ["serena"])
    ctx = (getattr(settings, "SERENA_CONTEXT", "agent") or "agent").strip()
    transport = (getattr(settings, "SERENA_TRANSPORT", "stdio") or "stdio").strip().lower()

    cmd = [command, *args, "--project", project]
    if ctx:
        cmd += ["--context", ctx]

    # Build connections map for MultiServerMCPClient
    connections: Dict[str, Dict[str, Any]] = {}

    if transport == "stdio":
        exe = _resolve_executable(getattr(settings, "SERENA_COMMAND", "uvx") or "uvx")
        base_args: List[str] = list(getattr(settings, "SERENA_ARGS", []) or [])

        # ensure / override --project
        if "--project" in base_args:
            for i, tok in enumerate(base_args):
                if tok == "--project" and i + 1 < len(base_args):
                    base_args[i + 1] = project
                    break
        else:
            base_args += ["--project", project]

        # ensure / override --context
        ctx = (getattr(settings, "SERENA_CONTEXT", "agent") or "agent").strip()
        if "--context" in base_args:
            for i, tok in enumerate(base_args):
                if tok == "--context" and i + 1 < len(base_args):
                    base_args[i + 1] = ctx
                    break
        else:
            base_args += ["--context", ctx]

        logger.info("Starting Serena MCP (stdio): %s %s", exe, " ".join(base_args))
        connections["serena"] = {"transport": "stdio", "command": exe, "args": base_args}

    elif transport == "streamable_http":
        url = "http://127.0.0.1:9121/mcp"
        logger.info("Using Serena MCP (streamable_http) at %s", url)
        connections["serena"] = {"transport": "streamable_http", "url": url}

    else:
        url = "http://127.0.0.1:9121/mcp"
        logger.info("Using Serena MCP (sse) at %s", url)
        connections["serena"] = {"transport": "sse", "url": url}

    client = MultiServerMCPClient(connections=cast("dict[str, Any]", connections))

    last_err: Exception | None = None
    for attempt in range(5):
        try:
            cm = client.session("serena")
            session = await cm.__aenter__()  # keep open for this request
            closers: List[Callable[..., Any]] = getattr(request.state, "_serena_close", None) or []
            request.state._serena_close = closers
            closers.append(cm.__aexit__)

            tools: List[BaseTool] = list(await load_mcp_tools(session))

            # ---- Filter to allowed coding tools only (plus optional shell) ----
            allowed = set(getattr(settings, "SERENA_ALLOWED_TOOL_NAMES", []) or [])
            if getattr(settings, "SERENA_ALLOW_SHELL", False):
                allowed.add("execute_shell_command")

            if allowed:
                tools = [t for t in tools if getattr(t, "name", "") in allowed]

            names = [getattr(t, "name", "") for t in tools]
            logger.info("Serena tools bound: %s", names)

            # Sanity: warn if write-capable tools are missing (agent won't be able to edit)
            required_writes = {
                "create_text_file",
                "replace_regex",
                "insert_after_symbol",
                "insert_before_symbol",
                "replace_symbol_body",
                "rename_symbol",
            }
            missing = sorted(required_writes - set(names))
            if missing:
                logger.warning("Write-capable tools missing: %s", missing)

            # ---- Patch: tolerant create_text_file with optional content ----
            orig_create = next((t for t in tools if getattr(t, "name", "") == "create_text_file"), None)
            if orig_create:
                tools = [t for t in tools if getattr(t, "name", "") != "create_text_file"]
                orig_create_tool: BaseTool = cast(BaseTool, orig_create)

                class _CreateArgs(BaseModel):
                    relative_path: str = Field(..., description="Path relative to project root.")
                    content: Optional[str] = Field(None, description="If omitted, a minimal stub will be written.")

                def _stub_for(path: str) -> str:
                    p = path.lower()
                    base = os.path.splitext(os.path.basename(path))[0]
                    ident = "".join(part.title() for part in base.replace("-", " ").replace("_", " ").split())
                    if p.endswith(".ts"):  return f"/** Auto-stub */\nexport class {ident} {{}}\n"
                    if p.endswith(".tsx"): return f"/** Auto-stub */\nexport default function {ident}(){{return null;}}\n"
                    if p.endswith(".js"):  return "// Auto-stub\n"
                    if p.endswith(".md"):  return f"# {ident}\n"
                    return "\n"

                async def _create_text_file_safe(relative_path: str, content: Optional[str] = None):
                    payload = {
                        "relative_path": relative_path,
                        "content": (content if (content and content.strip()) else _stub_for(relative_path)),
                    }
                    if hasattr(orig_create_tool, "ainvoke"):
                        return await getattr(orig_create_tool, "ainvoke")(payload)  # type: ignore
                    if hasattr(orig_create_tool, "arun"):
                        return await getattr(orig_create_tool, "arun")(payload)     # type: ignore
                    if hasattr(orig_create_tool, "invoke"):
                        return getattr(orig_create_tool, "invoke")(payload)        # type: ignore
                    if hasattr(orig_create_tool, "run"):
                        return getattr(orig_create_tool, "run")(payload)           # type: ignore
                    raise RuntimeError("create_text_file tool has no callable interface")

                tools.append(
                    StructuredTool.from_function(
                        func=_create_text_file_safe,
                        name="create_text_file",
                        description="Create a new text file. If 'content' is omitted, writes a minimal, valid stub.",
                        args_schema=_CreateArgs,
                    )
                )
            # ---------------------------------------------

            if tools:
                return tools
            last_err = RuntimeError("Serena session opened but returned 0 allowed tools")
        except (McpError, EndOfStream, ConnectionError, RuntimeError) as e:
            last_err = e
            await asyncio.sleep(0.8 * (attempt + 1))

    raise RuntimeError(
        "Serena MCP connection failed/exposed no allowed tools. "
        f"cmd={' '.join(cmd)} | project={project} | context={ctx} | transport={transport}. Last error: {last_err}"
    )


async def close_serena(request: Request) -> None:
    closers = getattr(request.state, "_serena_close", None) or []
    for aexit in closers:
        try:
            await aexit(None, None, None)  # type: ignore
        except Exception:
            pass
    request.state._serena_close = []
