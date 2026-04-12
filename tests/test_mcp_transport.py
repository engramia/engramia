# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""P1 — T-03: MCP server transport layer tests.

Covers the async interface on top of _dispatch():
- list_tools()   : returns the 7 registered tools with correct names and schemas.
- call_tool()    : wraps _dispatch() result as JSON in TextContent; wraps
                   exceptions as "Error: ..." TextContent; calls _dispatch with
                   the correct (mem, name, arguments) triple.
- _get_mem()     : singleton — Memory is created exactly once; subsequent calls
                   return the same instance.

The ``mcp`` package is stubbed at module level so these tests run without the
real MCP SDK installed.  Unlike test_mcp.py (which only tests _dispatch), this
file registers *corrected* stubs that preserve the original async function when
@server.list_tools() / @server.call_tool() decorators are applied, enabling
direct invocation.
"""

from __future__ import annotations

import json
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Corrected MCP stubs
#
# The shared stub in test_mcp.py uses _noop_decorator which returns _inner
# when called with a function (causing TypeError on invocation).  This file
# uses a smarter decorator factory that returns the original function
# unchanged, so list_tools / call_tool remain callable.
# ---------------------------------------------------------------------------


def _corrected_noop(*a, **kw):
    """No-op decorator compatible with both @deco and @deco() usage patterns.

    When called with a single callable argument (the function being decorated),
    return it unchanged.  When called with no args (decorator factory), return
    a pass-through inner decorator.
    """
    if len(a) == 1 and callable(a[0]):
        return a[0]

    def _inner(fn):
        return fn

    return _inner


class _CorrectedFakeServer:
    def __init__(self, *a, **kw):
        pass

    def list_tools(self):
        return _corrected_noop

    def call_tool(self):
        return _corrected_noop


_mcp_stub = ModuleType("mcp")
_mcp_server = ModuleType("mcp.server")
_mcp_server_stdio = ModuleType("mcp.server.stdio")
_mcp_server_models = ModuleType("mcp.server.models")
_mcp_types = ModuleType("mcp.types")

_mcp_server.Server = _CorrectedFakeServer
_mcp_server_models.InitializationOptions = MagicMock
_mcp_types.TextContent = MagicMock
_mcp_types.Tool = MagicMock

# Force-register stubs so the server module always uses the corrected version.
# We also evict any previously cached engramia.mcp.server so a fresh import
# picks up _CorrectedFakeServer (and list_tools / call_tool are real async fns).
for _name, _mod in [
    ("mcp", _mcp_stub),
    ("mcp.server", _mcp_server),
    ("mcp.server.stdio", _mcp_server_stdio),
    ("mcp.server.models", _mcp_server_models),
    ("mcp.types", _mcp_types),
]:
    sys.modules[_name] = _mod

sys.modules.pop("engramia.mcp.server", None)  # force fresh import below

import engramia.mcp.server as _server_mod  # noqa: E402
from engramia.mcp.server import (  # noqa: E402
    _get_mem,
    call_tool,
    list_tools,
)

# ---------------------------------------------------------------------------
# Helper replacements for MagicMock stubs — allow attribute inspection
# ---------------------------------------------------------------------------


class _TextContent:
    """Minimal stand-in for mcp.types.TextContent."""

    def __init__(self, *, type: str, text: str) -> None:
        self.type = type
        self.text = text


class _Tool:
    """Minimal stand-in for mcp.types.Tool."""

    def __init__(self, *, name: str, description: str, inputSchema: dict) -> None:
        self.name = name
        self.description = description
        self.inputSchema = inputSchema


@pytest.fixture()
def real_text_content():
    """Replace mcp.types.TextContent with _TextContent for the test duration."""
    original = _mcp_types.TextContent
    _mcp_types.TextContent = _TextContent
    yield _TextContent
    _mcp_types.TextContent = original


@pytest.fixture()
def real_tool():
    """Replace mcp.types.Tool with _Tool for the test duration."""
    original = _mcp_types.Tool
    _mcp_types.Tool = _Tool
    yield _Tool
    _mcp_types.Tool = original


# ---------------------------------------------------------------------------
# T-03a: list_tools()
# ---------------------------------------------------------------------------

_EXPECTED_TOOL_NAMES = {
    "engramia_learn",
    "engramia_recall",
    "engramia_evaluate",
    "engramia_compose",
    "engramia_feedback",
    "engramia_metrics",
    "engramia_aging",
}


class TestListTools:
    """list_tools() returns the 7 registered MCP tools with correct metadata."""

    async def test_returns_seven_tools(self, real_tool):
        tools = await list_tools()
        assert len(tools) == 7

    async def test_all_expected_tool_names_present(self, real_tool):
        tools = await list_tools()
        names = {t.name for t in tools}
        assert names == _EXPECTED_TOOL_NAMES

    async def test_each_tool_has_non_empty_description(self, real_tool):
        tools = await list_tools()
        for tool in tools:
            assert isinstance(tool.description, str)
            assert len(tool.description) > 0, f"Tool {tool.name!r} has empty description"

    async def test_each_tool_has_object_input_schema(self, real_tool):
        tools = await list_tools()
        for tool in tools:
            assert isinstance(tool.inputSchema, dict), f"Tool {tool.name!r} has non-dict inputSchema"
            assert tool.inputSchema.get("type") == "object", f"Tool {tool.name!r} schema type != 'object'"

    async def test_learn_tool_requires_task_code_eval_score(self, real_tool):
        tools = await list_tools()
        learn = next(t for t in tools if t.name == "engramia_learn")
        required = set(learn.inputSchema.get("required", []))
        assert "task" in required
        assert "code" in required
        assert "eval_score" in required

    async def test_recall_tool_requires_task(self, real_tool):
        tools = await list_tools()
        recall = next(t for t in tools if t.name == "engramia_recall")
        assert "task" in recall.inputSchema.get("required", [])

    async def test_evaluate_tool_requires_task_and_code(self, real_tool):
        tools = await list_tools()
        ev = next(t for t in tools if t.name == "engramia_evaluate")
        required = set(ev.inputSchema.get("required", []))
        assert "task" in required
        assert "code" in required

    async def test_metrics_and_aging_have_no_required_fields(self, real_tool):
        tools = await list_tools()
        for name in ("engramia_metrics", "engramia_aging"):
            tool = next(t for t in tools if t.name == name)
            assert tool.inputSchema.get("required", []) == []


# ---------------------------------------------------------------------------
# T-03b: call_tool() — async wrapping layer
# ---------------------------------------------------------------------------


class TestCallToolDispatch:
    """call_tool() wraps _dispatch() result as JSON TextContent."""

    async def test_happy_path_returns_json_text_content(self, real_text_content):
        dispatch_result = {"stored": True, "pattern_count": 5}
        with (
            patch("engramia.mcp.server._get_mem", return_value=MagicMock()),
            patch("engramia.mcp.server._dispatch", return_value=dispatch_result),
        ):
            result = await call_tool("engramia_learn", {"task": "T", "code": "C", "eval_score": 8.0})

        assert isinstance(result, list)
        assert len(result) == 1
        tc = result[0]
        assert tc.type == "text"
        assert json.loads(tc.text) == dispatch_result

    async def test_json_is_indented(self, real_text_content):
        """Response JSON uses indent=2 (matches server implementation)."""
        dispatch_result = {"runs": 10, "success_rate": 0.8}
        with (
            patch("engramia.mcp.server._get_mem", return_value=MagicMock()),
            patch("engramia.mcp.server._dispatch", return_value=dispatch_result),
        ):
            result = await call_tool("engramia_metrics", {})

        text = result[0].text
        assert "\n" in text
        assert "  " in text  # 2-space indent

    async def test_dispatch_exception_returns_error_text_content(self, real_text_content):
        """When _dispatch raises, call_tool returns 'Error: <msg>' not a bare exception."""
        with (
            patch("engramia.mcp.server._get_mem", return_value=MagicMock()),
            patch("engramia.mcp.server._dispatch", side_effect=ValueError("bad argument")),
        ):
            result = await call_tool("engramia_learn", {})

        assert len(result) == 1
        tc = result[0]
        assert tc.type == "text"
        assert tc.text.startswith("Error:")
        assert "bad argument" in tc.text

    async def test_unknown_tool_error_is_wrapped_not_raised(self, real_text_content):
        """ValueError from _dispatch for unknown tool is wrapped, not propagated."""
        with patch("engramia.mcp.server._get_mem", return_value=MagicMock()):
            result = await call_tool("nonexistent_tool", {})

        assert len(result) == 1
        assert "Error:" in result[0].text

    async def test_dispatch_called_with_mem_name_arguments(self, real_text_content):
        """_dispatch must receive the Memory instance, tool name, and arguments dict."""
        fake_mem = MagicMock()
        arguments = {"task": "test task", "limit": 3}

        with (
            patch("engramia.mcp.server._get_mem", return_value=fake_mem),
            patch("engramia.mcp.server._dispatch", return_value=[]) as mock_dispatch,
        ):
            await call_tool("engramia_recall", arguments)

        mock_dispatch.assert_called_once_with(fake_mem, "engramia_recall", arguments)

    async def test_empty_list_result_serialised_as_json_array(self, real_text_content):
        """An empty list result serialises as '[]', not an error."""
        with (
            patch("engramia.mcp.server._get_mem", return_value=MagicMock()),
            patch("engramia.mcp.server._dispatch", return_value=[]),
        ):
            result = await call_tool("engramia_recall", {"task": "anything"})

        assert json.loads(result[0].text) == []

    async def test_arbitrary_runtime_error_wrapped_as_error_text(self, real_text_content):
        """Any exception from _dispatch is caught and returned as 'Error: ...'."""
        with (
            patch("engramia.mcp.server._get_mem", return_value=MagicMock()),
            patch("engramia.mcp.server._dispatch", side_effect=RuntimeError("unexpected")),
        ):
            result = await call_tool("engramia_aging", {})

        assert result[0].text.startswith("Error:")
        assert "unexpected" in result[0].text


# ---------------------------------------------------------------------------
# T-03c: _get_mem() singleton pattern
# ---------------------------------------------------------------------------


class TestGetMemSingleton:
    """_get_mem() must create Memory exactly once and cache the instance."""

    def test_returns_same_instance_on_repeated_calls(self):
        """Two consecutive calls return the identical object."""
        original_mem = _server_mod._mem
        try:
            _server_mod._mem = None  # reset singleton

            with (
                patch("engramia.mcp.server.make_storage", return_value=MagicMock()),
                patch("engramia.mcp.server.make_embeddings", return_value=MagicMock()),
                patch("engramia.mcp.server.make_llm", return_value=MagicMock()),
                patch("engramia.mcp.server.Memory") as mock_memory_cls,
            ):
                mock_memory_cls.return_value = MagicMock(name="mem_instance")
                mem1 = _get_mem()
                mem2 = _get_mem()

            assert mem1 is mem2
            mock_memory_cls.assert_called_once()  # constructed only once
        finally:
            _server_mod._mem = original_mem

    def test_memory_created_with_storage_embeddings_llm(self):
        """_get_mem() passes storage, embeddings, and llm to the Memory constructor."""
        original_mem = _server_mod._mem
        try:
            _server_mod._mem = None

            fake_storage = MagicMock(name="storage")
            fake_embeddings = MagicMock(name="embeddings")
            fake_llm = MagicMock(name="llm")

            with (
                patch("engramia.mcp.server.make_storage", return_value=fake_storage),
                patch("engramia.mcp.server.make_embeddings", return_value=fake_embeddings),
                patch("engramia.mcp.server.make_llm", return_value=fake_llm),
                patch("engramia.mcp.server.Memory") as mock_memory_cls,
            ):
                _get_mem()

            mock_memory_cls.assert_called_once_with(
                storage=fake_storage,
                embeddings=fake_embeddings,
                llm=fake_llm,
            )
        finally:
            _server_mod._mem = original_mem

    def test_existing_mem_returned_without_reconstruction(self):
        """If _mem is already set, _get_mem() returns it without calling Memory()."""
        original_mem = _server_mod._mem
        try:
            sentinel = MagicMock(name="sentinel_mem")
            _server_mod._mem = sentinel

            with patch("engramia.mcp.server.Memory") as mock_memory_cls:
                result = _get_mem()

            assert result is sentinel
            mock_memory_cls.assert_not_called()
        finally:
            _server_mod._mem = original_mem
