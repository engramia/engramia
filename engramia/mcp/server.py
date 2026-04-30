# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""MCP server for Engramia (stdio transport).

Exposes Engramia operations as MCP tools for use with Claude Desktop, Cursor,
Windsurf, VS Code Copilot, and any other MCP-compatible client.

Configuration via environment variables (same as the REST API):
    ENGRAMIA_STORAGE        json | postgres          (default: json)
    ENGRAMIA_DATA_PATH      ./engramia_data          (json only)
    ENGRAMIA_DATABASE_URL   postgresql://...         (postgres only)
    ENGRAMIA_LLM_PROVIDER   openai                   (default: openai)
    ENGRAMIA_LLM_MODEL      gpt-4.1                  (default: gpt-4.1)
    OPENAI_API_KEY       sk-...

Usage (stdio transport):
    engramia-mcp

Claude Desktop config (~/.config/claude/claude_desktop_config.json):
    {
      "mcpServers": {
        "engramia": {
          "command": "engramia-mcp",
          "env": {
            "ENGRAMIA_DATA_PATH": "/path/to/engramia_data",
            "OPENAI_API_KEY": "sk-..."
          }
        }
      }
    }

Architecture note:
    Tool definitions and dispatch logic live in ``engramia/mcp/tools.py`` and
    ``engramia/mcp/dispatch.py`` so the hosted Streamable HTTP transport
    (``engramia/mcp/http_server.py``) can share them without duplication. This
    module is the **stdio glue** — it wires the shared catalog/dispatch into
    the stdio MCP transport and runs the asyncio event loop. The legacy
    module-level symbols (``_dispatch``, ``_ALL_TOOLS``, ``_TOOL_*``) remain
    exported for tests and any external code that imported them prior to the
    refactor.
"""

import asyncio
import json
import logging

import mcp.server.stdio
import mcp.types as types
from mcp.server import Server
from mcp.server.models import InitializationOptions

from engramia import Memory, __version__
from engramia._factory import make_embeddings, make_llm, make_storage
from engramia.mcp import dispatch as _shared_dispatch
from engramia.mcp import tools as _shared_tools

_log = logging.getLogger(__name__)

server: Server = Server("engramia")
_mem: Memory | None = None


def _get_mem() -> Memory:
    global _mem
    if _mem is None:
        _mem = Memory(
            storage=make_storage(),
            embeddings=make_embeddings(),
            llm=make_llm(),
        )
    return _mem


# ---------------------------------------------------------------------------
# Backward-compatible exports — pre-refactor callers (mostly tests) imported
# these module-level names directly. Now sourced from the shared catalog.
# ---------------------------------------------------------------------------

_TOOL_LEARN = _shared_tools.get_entry("engramia_learn").tool  # type: ignore[union-attr]
_TOOL_RECALL = _shared_tools.get_entry("engramia_recall").tool  # type: ignore[union-attr]
_TOOL_EVALUATE = _shared_tools.get_entry("engramia_evaluate").tool  # type: ignore[union-attr]
_TOOL_COMPOSE = _shared_tools.get_entry("engramia_compose").tool  # type: ignore[union-attr]
_TOOL_FEEDBACK = _shared_tools.get_entry("engramia_feedback").tool  # type: ignore[union-attr]
_TOOL_METRICS = _shared_tools.get_entry("engramia_metrics").tool  # type: ignore[union-attr]
_TOOL_AGING = _shared_tools.get_entry("engramia_aging").tool  # type: ignore[union-attr]

# Stdio is unscoped self-host — exposes the full catalog (including the two
# tools added in Phase 6.6 for the hosted transport: evolve, analyze_failures).
_ALL_TOOLS: list[types.Tool] = _shared_tools.stdio_tools()


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return _ALL_TOOLS


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    mem = await asyncio.to_thread(_get_mem)

    try:
        result = await asyncio.to_thread(_dispatch, mem, name, arguments)
    except Exception as exc:
        _log.exception("MCP tool %r failed", name)
        return [types.TextContent(type="text", text=f"Error: {exc}")]

    return [types.TextContent(type="text", text=json.dumps(result, indent=2))]


def _dispatch(mem: Memory, name: str, arguments: dict) -> object:
    """Synchronous dispatch — runs in a thread via asyncio.to_thread.

    Thin shim over :func:`engramia.mcp.dispatch.dispatch_to_memory`. The shim
    exists for backward compatibility with tests that monkeypatch
    ``engramia.mcp.server._dispatch``; new code should call
    ``dispatch.dispatch_to_memory`` directly.
    """
    return _shared_dispatch.dispatch_to_memory(mem, name, arguments)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def _run() -> None:
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(  # type: ignore[call-arg]
                server_name="engramia",
                server_version=__version__,
            ),
        )


def main() -> None:
    """Entry point for ``engramia-mcp`` CLI command (stdio transport)."""
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(_run())


if __name__ == "__main__":
    main()
