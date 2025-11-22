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

class _InsertTextArgs(BaseModel):
    relative_path: str
    name_path: str
    text_to_insert: str

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
    spawn_cmd: Optional[List[str]] = None

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
        spawn_cmd = [exe, *base_args]
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
            


            # ---- Patch: normalize symbol tools + safe fallbacks ----------------
            def _get(name: str) -> Optional[BaseTool]:
                return next((t for t in tools if getattr(t, "name", "") == name), None)

            def _normalize_name_path(name_path: str) -> str:
                # Accept dotted or slashed paths; normalize to slash
                np = (name_path or "").strip()
                np = np.replace("\\", "/").replace("//", "/").replace(".", "/")
                return np.strip("/")

            # one place to call MCP tools regardless of arun/ainvoke/invoke/run
            async def _call(tool: Optional[BaseTool], payload: dict):
                if tool is None:
                    raise RuntimeError(f"Requested tool is not available. payload={payload}")

                # Readiness/backoff settings
                max_retries = int(getattr(settings, "SERENA_LS_READY_MAX_RETRIES", 6))
                base_sleep = float(getattr(settings, "SERENA_LS_READY_BASE_SLEEP", 0.75))

                # Common error substrings we see while TS/LS is still spinning up
                ls_err_markers = (
                    "language server", "tsserver", "initialize", "index", "indexing",
                    "not ready", "timeout waiting", "LSP", "server to become ready"
                )

                for attempt in range(max_retries + 1):
                    try:
                        if hasattr(tool, "ainvoke"):
                            return await getattr(tool, "ainvoke")(payload)  # type: ignore
                        if hasattr(tool, "arun"):
                            return await getattr(tool, "arun")(payload)     # type: ignore
                        if hasattr(tool, "invoke"):
                            return getattr(tool, "invoke")(payload)         # type: ignore
                        if hasattr(tool, "run"):
                            return getattr(tool, "run")(payload)            # type: ignore
                        raise RuntimeError(f"Tool {getattr(tool,'name','')} has no callable interface")
                    except Exception as e:
                        # If it smells like "LS not ready" and we still have retries, back off then retry
                        err_txt = (str(e) or "").lower()
                        if any(m in err_txt for m in ls_err_markers) and attempt < max_retries:
                            sleep_for = base_sleep * (attempt + 1)
                            logger.warning(
                                "Serena tool '%s' hit LS-not-ready (%s). Retrying in %.2fs (attempt %d/%d). Payload=%r",
                                getattr(tool, "name", ""), e, sleep_for, attempt + 1, max_retries, payload
                            )
                            await asyncio.sleep(sleep_for)
                            continue
                        # otherwise, bubble it up
                        raise

            _find_symbol = _get("find_symbol")
            _replace_symbol_body = _get("replace_symbol_body")
            _get_symbols_overview = _get("get_symbols_overview")
            _insert_after_symbol = _get("insert_after_symbol")
            _insert_before_symbol = _get("insert_before_symbol")
            _rename_symbol = _get("rename_symbol")
            _find_refs = _get("find_referencing_symbols")

            # ---- Wrap find_symbol to normalize name_path --------------------------------
            if _find_symbol:
                tools = [t for t in tools if getattr(t, "name", "") != "find_symbol"]

                class _FindArgs(BaseModel):
                    name_path: str
                    relative_path: Optional[str] = Field(None, description="Optional file to constrain the search")
                    include_body: Optional[bool] = False
                    depth: Optional[int] = 0

                async def _find_symbol_safe(
                    name_path: str,
                    relative_path: Optional[str] = None,
                    include_body: Optional[bool] = False,
                    depth: Optional[int] = 0,
                ):
                    np = _normalize_name_path(name_path)
                    payload = {"name_path": np, "include_body": bool(include_body), "depth": int(depth or 0)}
                    if relative_path:
                        payload["relative_path"] = relative_path
                    return await _call(_find_symbol, payload)

                tools.append(
                    StructuredTool.from_function(
                        func=_find_symbol_safe,
                        name="find_symbol",
                        description="Find a symbol by normalized name_path; accepts dotted or slashed paths.",
                        args_schema=_FindArgs,
                    )
                )

            # ---- Wrap insert_after_symbol to normalize name_path ------------------------
            if _insert_after_symbol:
                tools = [t for t in tools if getattr(t, "name", "") != "insert_after_symbol"]

                async def _insert_after_symbol_safe(relative_path: str, name_path: str, text_to_insert: str):
                    np = _normalize_name_path(name_path)
                    return await _call(_insert_after_symbol, {
                        "relative_path": relative_path,
                        "name_path": np,
                        "text_to_insert": text_to_insert,
                    })

                tools.append(
                    StructuredTool.from_function(
                        func=_insert_after_symbol_safe,
                        name="insert_after_symbol",
                        description="Insert text after a normalized symbol path.",
                        args_schema=_InsertTextArgs,
                    )
                )

            # ---- Wrap insert_before_symbol to normalize name_path -----------------------
            if _insert_before_symbol:
                tools = [t for t in tools if getattr(t, "name", "") != "insert_before_symbol"]

                async def _insert_before_symbol_safe(relative_path: str, name_path: str, text_to_insert: str):
                    np = _normalize_name_path(name_path)
                    return await _call(_insert_before_symbol, {
                        "relative_path": relative_path,
                        "name_path": np,
                        "text_to_insert": text_to_insert,
                    })

                tools.append(
                    StructuredTool.from_function(
                        func=_insert_before_symbol_safe,
                        name="insert_before_symbol",
                        description="Insert text before a normalized symbol path.",
                        args_schema=_InsertTextArgs,  # reuse same schema
                    )
                )

            # ---- Wrap replace_symbol_body with preflight + fallbacks --------------------
            if _replace_symbol_body:
                tools = [t for t in tools if getattr(t, "name", "") != "replace_symbol_body"]

                class _ReplaceArgs(BaseModel):
                    relative_path: str
                    name_path: str
                    new_body: str

                async def _replace_symbol_body_safe(relative_path: str, name_path: str, new_body: str):
                    np = _normalize_name_path(name_path)

                    # Preflight: does symbol exist?
                    symbol_exists = False
                    if _find_symbol:
                        try:
                            res = await _call(_find_symbol, {
                                "relative_path": relative_path,
                                "name_path": np,
                                "include_body": False,
                                "depth": 0,
                            })
                            candidates = res.get("symbols") if isinstance(res, dict) else res
                            symbol_exists = bool(candidates)
                        except Exception as e:
                            logger.warning("find_symbol probe failed: %s", e)

                    # Fast path if it exists
                    if symbol_exists:
                        try:
                            return await _call(_replace_symbol_body, {
                                "relative_path": relative_path,
                                "name_path": np,
                                "new_body": new_body,
                            })
                        except Exception as e:
                            logger.warning("replace_symbol_body failed despite symbol existing: %s", e)

                    # Fallbacks…
                    text_to_insert = f"\n{new_body}\n"

                    # After last top-level symbol
                    last_name_path: Optional[str] = None
                    if _get_symbols_overview:
                        try:
                            ov = await _call(_get_symbols_overview, {"relative_path": relative_path})
                            syms = ov.get("symbols") if isinstance(ov, dict) else ov
                            if isinstance(syms, list) and syms:
                                last = syms[-1]
                                last_name_path = last.get("name_path") if isinstance(last, dict) else None
                        except Exception as e:
                            logger.warning("get_symbols_overview failed: %s", e)

                    if last_name_path and _insert_after_symbol:
                        try:
                            return await _call(_insert_after_symbol, {
                                "relative_path": relative_path,
                                "name_path": last_name_path,
                                "text_to_insert": text_to_insert,
                            })
                        except Exception as e:
                            logger.warning("insert_after_symbol fallback failed: %s", e)

                    # Before first top-level symbol
                    if _get_symbols_overview and _insert_before_symbol:
                        try:
                            ov = await _call(_get_symbols_overview, {"relative_path": relative_path})
                            syms = ov.get("symbols") if isinstance(ov, dict) else ov
                            if isinstance(syms, list) and syms:
                                first = syms[0]
                                first_np = first.get("name_path") if isinstance(first, dict) else None
                                if first_np:
                                    return await _call(_insert_before_symbol, {
                                        "relative_path": relative_path,
                                        "name_path": first_np,
                                        "text_to_insert": text_to_insert,
                                    })
                        except Exception as e:
                            logger.warning("insert_before_symbol fallback failed: %s", e)

                    # Append at EOF
                    _append = _get("replace_regex") or None
                    _read_file = _get("read_file") or None
                    if _append and _read_file:
                        try:
                            try:
                                await _call(_read_file, {"relative_path": relative_path})
                            except Exception:
                                _create = _get("create_text_file")
                                if _create:
                                    await _call(_create, {"relative_path": relative_path, "content": ""})

                            await _call(_append, {
                                "relative_path": relative_path,
                                "regex": r"\Z",
                                "replacement": f"\n{new_body}\n",
                                "allow_multiple_occurrences": False
                            })
                            return {"status": "ok", "fallback": "append_eof"}
                        except Exception as e:
                            logger.warning("append_eof fallback failed: %s", e)

                    raise RuntimeError(
                        f"Symbol '{np}' not found in {relative_path}; replace failed and fallbacks could not insert."
                    )

                tools.append(
                    StructuredTool.from_function(
                        func=_replace_symbol_body_safe,
                        name="replace_symbol_body",
                        description=(
                            "Replace the body of a symbol by normalized name_path. "
                            "If the symbol is missing, falls back to a safe insert in the file."
                        ),
                        args_schema=_ReplaceArgs,
                    )
                )

            # ---- Wrap rename_symbol to normalize name_path ------------------------------
            if _rename_symbol:
                tools = [t for t in tools if getattr(t, "name", "") != "rename_symbol"]

                class _RenameArgs(BaseModel):
                    relative_path: str
                    name_path: str
                    new_name: str

                async def _rename_symbol_safe(relative_path: str, name_path: str, new_name: str):
                    np = _normalize_name_path(name_path)
                    return await _call(_rename_symbol, {
                        "relative_path": relative_path,
                        "name_path": np,
                        "new_name": new_name,
                    })

                tools.append(
                    StructuredTool.from_function(
                        func=_rename_symbol_safe,
                        name="rename_symbol",
                        description="Rename a symbol (normalized name_path).",
                        args_schema=_RenameArgs,
                    )
                )

            # ---- Wrap find_referencing_symbols to normalize name_path -------------------
            if _find_refs:
                tools = [t for t in tools if getattr(t, "name", "") != "find_referencing_symbols"]

                class _FindRefsArgs(BaseModel):
                    name_path: str
                    relative_path: Optional[str] = None

                async def _find_referencing_symbols_safe(name_path: str, relative_path: Optional[str] = None):
                    np = _normalize_name_path(name_path)
                    payload = {"name_path": np}
                    if relative_path:
                        payload["relative_path"] = relative_path
                    return await _call(_find_refs, payload)

                tools.append(
                    StructuredTool.from_function(
                        func=_find_referencing_symbols_safe,
                        name="find_referencing_symbols",
                        description="Find references to a symbol (normalized name_path).",
                        args_schema=_FindRefsArgs,
                    )
                )
            # ---------------------------------------------------------------------------



            if tools:
                return tools
            last_err = RuntimeError("Serena session opened but returned 0 allowed tools")
        except (McpError, EndOfStream, ConnectionError, RuntimeError) as e:
            last_err = e
            await asyncio.sleep(0.8 * (attempt + 1))

    raise RuntimeError(
        "Serena MCP connection failed/exposed no allowed tools. "
        f"cmd={' '.join(spawn_cmd or cmd)} | project={project} | context={ctx} | transport={transport}. "
        f"Last error: {last_err}"
    )


async def close_serena(request: Request) -> None:
    closers = getattr(request.state, "_serena_close", None) or []
    for aexit in closers:
        try:
            await aexit(None, None, None)  # type: ignore
        except Exception:
            pass
    request.state._serena_close = []
