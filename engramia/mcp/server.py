# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""MCP server for Engramia.

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
# Tool definitions
# ---------------------------------------------------------------------------


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="engramia_learn",
            description=(
                "Record a successful agent run so Engramia can store it as a reusable pattern. "
                "Stores the task, code, and eval score."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Natural language task description."},
                    "code": {"type": "string", "description": "Agent source code / solution."},
                    "eval_score": {
                        "type": "number",
                        "description": "Quality score 0-10.",
                        "minimum": 0,
                        "maximum": 10,
                    },
                    "output": {"type": "string", "description": "Captured stdout (optional)."},
                },
                "required": ["task", "code", "eval_score"],
            },
        ),
        types.Tool(
            name="engramia_recall",
            description=(
                "Find stored patterns most relevant to a new task using semantic search with eval-score weighting."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Task to find relevant patterns for."},
                    "limit": {
                        "type": "integer",
                        "description": "Max results (1-50).",
                        "minimum": 1,
                        "maximum": 50,
                        "default": 5,
                    },
                },
                "required": ["task"],
            },
        ),
        types.Tool(
            name="engramia_evaluate",
            description=(
                "Run N independent LLM evaluations on an agent run and return median score, variance, and feedback."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task": {"type": "string"},
                    "code": {"type": "string"},
                    "output": {"type": "string", "description": "Captured stdout (optional)."},
                    "num_evals": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10,
                        "default": 3,
                    },
                },
                "required": ["task", "code"],
            },
        ),
        types.Tool(
            name="engramia_compose",
            description=(
                "[Experimental] Decompose a high-level task into a validated multi-agent pipeline. "
                "Each stage is matched against stored patterns."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "High-level task to decompose."},
                },
                "required": ["task"],
            },
        ),
        types.Tool(
            name="engramia_feedback",
            description=("Return top recurring quality issues suitable for injection into agent prompts."),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_type": {
                        "type": "string",
                        "description": "Filter by task type prefix (optional).",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 20,
                        "default": 4,
                    },
                },
            },
        ),
        types.Tool(
            name="engramia_metrics",
            description="Return aggregate Engramia statistics: runs, success rate, pattern count, reuse rate.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="engramia_aging",
            description=(
                "Apply time-based decay to all stored patterns (2%/week) and prune those below the minimum threshold."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


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
    """Synchronous dispatch — runs in a thread via asyncio.to_thread."""
    if name == "engramia_learn":
        result = mem.learn(
            task=arguments["task"],
            code=arguments["code"],
            eval_score=float(arguments["eval_score"]),
            output=arguments.get("output"),
        )
        return {"stored": result.stored, "pattern_count": result.pattern_count}

    if name == "engramia_recall":
        matches = mem.recall(
            task=arguments["task"],
            limit=int(arguments.get("limit", 5)),
        )
        return [
            {
                "similarity": m.similarity,
                "reuse_tier": m.reuse_tier,
                "pattern_key": m.pattern_key,
                "task": m.pattern.task,
                "success_score": m.pattern.success_score,
                "code": m.pattern.design.get("code"),
            }
            for m in matches
        ]

    if name == "engramia_evaluate":
        ev = mem.evaluate(
            task=arguments["task"],
            code=arguments["code"],
            output=arguments.get("output"),
            num_evals=int(arguments.get("num_evals", 3)),
        )
        return {
            "median_score": ev.median_score,
            "variance": ev.variance,
            "high_variance": ev.high_variance,
            "feedback": ev.feedback,
            "adversarial_detected": ev.adversarial_detected,
        }

    if name == "engramia_compose":
        pipeline = mem.compose(task=arguments["task"])
        return {
            "task": pipeline.task,
            "valid": pipeline.valid,
            "contract_errors": pipeline.contract_errors,
            "stages": [
                {
                    "name": s.name,
                    "task": s.task,
                    "reads": s.reads,
                    "writes": s.writes,
                    "reuse_tier": s.reuse_tier,
                }
                for s in pipeline.stages
            ],
        }

    if name == "engramia_feedback":
        feedback = mem.get_feedback(
            task_type=arguments.get("task_type"),
            limit=int(arguments.get("limit", 4)),
        )
        return {"feedback": feedback}

    if name == "engramia_metrics":
        m = mem.metrics
        reuse_rate = m.pipeline_reuse / m.runs if m.runs > 0 else 0.0
        return {
            "runs": m.runs,
            "success_rate": m.success_rate,
            "avg_eval_score": m.avg_eval_score,
            "pattern_count": m.pattern_count,
            "reuse_rate": reuse_rate,
        }

    if name == "engramia_aging":
        pruned = mem.run_aging()
        return {"pruned": pruned}

    raise ValueError(f"Unknown tool: {name!r}")


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
