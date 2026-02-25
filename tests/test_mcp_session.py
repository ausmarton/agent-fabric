"""Tests for MCPSessionManager and mcp_tool_to_openai_def converter.

All tests are fully mocked — no real MCP server required.
The 'mcp' package import in session.py is patched out via sys.modules injection
so these tests work even when the optional dep is not installed.
"""
from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Inject mock mcp modules before importing the module under test.
# This allows tests to run even if 'mcp' is not installed.
# ---------------------------------------------------------------------------

def _make_mock_mcp_modules():
    """Return a dict of mock mcp sub-modules for sys.modules injection."""
    mock_mcp = MagicMock()
    mock_stdio_mod = MagicMock()
    mock_sse_mod = MagicMock()
    mock_client_mod = MagicMock()
    mock_client_mod.stdio = mock_stdio_mod
    mock_client_mod.sse = mock_sse_mod
    return {
        "mcp": mock_mcp,
        "mcp.client": mock_client_mod,
        "mcp.client.stdio": mock_stdio_mod,
        "mcp.client.sse": mock_sse_mod,
    }


# Inject before any import of session module happens.
for _k, _v in _make_mock_mcp_modules().items():
    sys.modules.setdefault(_k, _v)


# Now import after injection.
from agentic_concierge.config.schema import MCPServerConfig  # noqa: E402
from agentic_concierge.infrastructure.mcp.session import MCPSessionManager  # noqa: E402
from agentic_concierge.infrastructure.mcp.converter import mcp_tool_to_openai_def  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stdio_config(name: str = "test") -> MCPServerConfig:
    return MCPServerConfig(name=name, transport="stdio", command="npx", args=["-y", "server"])


def _sse_config(name: str = "test") -> MCPServerConfig:
    return MCPServerConfig(name=name, transport="sse", url="http://localhost:3000/sse")


def _make_session_mock() -> AsyncMock:
    """Return an async mock that behaves like a ClientSession."""
    session = AsyncMock()
    session.initialize = AsyncMock()
    return session


def _make_tool(name: str, description: str = "A tool", schema: Any = None) -> MagicMock:
    tool = MagicMock()
    tool.name = name
    tool.description = description
    tool.inputSchema = schema
    return tool


@asynccontextmanager
async def _noop_transport_cm(*_args, **_kwargs):
    """Simulate a transport context manager yielding (read, write) streams."""
    yield MagicMock(), MagicMock()


@asynccontextmanager
async def _session_cm(session_mock):
    """Simulate ClientSession used as an async context manager."""
    yield session_mock


# ---------------------------------------------------------------------------
# converter tests
# ---------------------------------------------------------------------------

def test_mcp_tool_to_openai_def_with_schema():
    """Converter wraps an MCP tool with its inputSchema into OpenAI format."""
    tool = _make_tool("my_tool", "Does something", schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]})
    result = mcp_tool_to_openai_def("mcp__srv__my_tool", tool)
    assert result["type"] == "function"
    assert result["function"]["name"] == "mcp__srv__my_tool"
    assert result["function"]["description"] == "Does something"
    assert result["function"]["parameters"]["properties"]["x"]["type"] == "string"


def test_mcp_tool_to_openai_def_none_schema_substitutes_empty():
    """Converter substitutes an empty schema when inputSchema is None."""
    tool = _make_tool("bare_tool", schema=None)
    result = mcp_tool_to_openai_def("mcp__srv__bare_tool", tool)
    params = result["function"]["parameters"]
    assert params == {"type": "object", "properties": {}, "required": []}


def test_mcp_tool_to_openai_def_empty_description():
    """Converter handles a tool with no description (None → empty string)."""
    tool = _make_tool("t", description=None, schema=None)
    result = mcp_tool_to_openai_def("mcp__srv__t", tool)
    assert result["function"]["description"] == ""


# ---------------------------------------------------------------------------
# MCPSessionManager.connect — stdio
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connect_stdio_calls_stdio_client():
    """connect() with stdio transport calls stdio_client and initializes the session."""
    session_mock = _make_session_mock()

    with (
        patch("agentic_concierge.infrastructure.mcp.session.StdioServerParameters", MagicMock()),
        patch("agentic_concierge.infrastructure.mcp.session.stdio_client", side_effect=_noop_transport_cm),
        patch("agentic_concierge.infrastructure.mcp.session.ClientSession", side_effect=lambda r, w: _session_cm(session_mock)),
        patch("agentic_concierge.infrastructure.mcp.session._MCP_AVAILABLE", True),
    ):
        mgr = MCPSessionManager(_stdio_config())
        await mgr.connect()

    session_mock.initialize.assert_awaited_once()


# ---------------------------------------------------------------------------
# MCPSessionManager.connect — SSE
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connect_sse_calls_sse_client():
    """connect() with sse transport calls sse_client and initializes the session."""
    session_mock = _make_session_mock()

    with (
        patch("agentic_concierge.infrastructure.mcp.session.sse_client", side_effect=_noop_transport_cm),
        patch("agentic_concierge.infrastructure.mcp.session.ClientSession", side_effect=lambda r, w: _session_cm(session_mock)),
        patch("agentic_concierge.infrastructure.mcp.session._MCP_AVAILABLE", True),
    ):
        mgr = MCPSessionManager(_sse_config())
        await mgr.connect()

    session_mock.initialize.assert_awaited_once()


# ---------------------------------------------------------------------------
# MCPSessionManager: mcp not available
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connect_raises_import_error_when_mcp_not_available():
    """connect() raises ImportError with a helpful message when mcp is not installed."""
    with patch("agentic_concierge.infrastructure.mcp.session._MCP_AVAILABLE", False):
        mgr = MCPSessionManager(_stdio_config())
        with pytest.raises(ImportError, match="mcp.*package"):
            await mgr.connect()


# ---------------------------------------------------------------------------
# MCPSessionManager.owns_tool
# ---------------------------------------------------------------------------

def test_owns_tool_true_for_prefixed_name():
    mgr = MCPSessionManager(_stdio_config("github"))
    assert mgr.owns_tool("mcp__github__create_issue") is True


def test_owns_tool_false_for_other_prefix():
    mgr = MCPSessionManager(_stdio_config("github"))
    assert mgr.owns_tool("mcp__jira__create_issue") is False


def test_owns_tool_false_for_native_tool():
    mgr = MCPSessionManager(_stdio_config("github"))
    assert mgr.owns_tool("shell") is False


# ---------------------------------------------------------------------------
# MCPSessionManager.list_tools
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_tools_returns_prefixed_openai_defs():
    """list_tools() converts MCP tools to OpenAI format with the server prefix."""
    session_mock = _make_session_mock()
    list_result = MagicMock()
    list_result.tools = [
        _make_tool("create_issue", "Create a GitHub issue", {"type": "object", "properties": {}}),
        _make_tool("list_prs", "List pull requests", None),
    ]
    session_mock.list_tools = AsyncMock(return_value=list_result)

    with (
        patch("agentic_concierge.infrastructure.mcp.session.StdioServerParameters", MagicMock()),
        patch("agentic_concierge.infrastructure.mcp.session.stdio_client", side_effect=_noop_transport_cm),
        patch("agentic_concierge.infrastructure.mcp.session.ClientSession", side_effect=lambda r, w: _session_cm(session_mock)),
        patch("agentic_concierge.infrastructure.mcp.session._MCP_AVAILABLE", True),
    ):
        mgr = MCPSessionManager(_stdio_config("github"))
        await mgr.connect()
        tools = await mgr.list_tools()

    assert len(tools) == 2
    assert tools[0]["function"]["name"] == "mcp__github__create_issue"
    assert tools[1]["function"]["name"] == "mcp__github__list_prs"


# ---------------------------------------------------------------------------
# MCPSessionManager.call_tool
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_call_tool_returns_result_on_success():
    """call_tool() strips prefix, calls session.call_tool, returns {'result': text}."""
    session_mock = _make_session_mock()
    content_item = MagicMock()
    content_item.text = "issue #42 created"
    call_result = MagicMock()
    call_result.isError = False
    call_result.content = [content_item]
    session_mock.call_tool = AsyncMock(return_value=call_result)

    with (
        patch("agentic_concierge.infrastructure.mcp.session.StdioServerParameters", MagicMock()),
        patch("agentic_concierge.infrastructure.mcp.session.stdio_client", side_effect=_noop_transport_cm),
        patch("agentic_concierge.infrastructure.mcp.session.ClientSession", side_effect=lambda r, w: _session_cm(session_mock)),
        patch("agentic_concierge.infrastructure.mcp.session._MCP_AVAILABLE", True),
    ):
        mgr = MCPSessionManager(_stdio_config("github"))
        await mgr.connect()
        result = await mgr.call_tool("mcp__github__create_issue", {"title": "bug"})

    session_mock.call_tool.assert_awaited_once_with("create_issue", {"title": "bug"})
    assert result == {"result": "issue #42 created"}


@pytest.mark.asyncio
async def test_call_tool_returns_error_on_is_error():
    """call_tool() returns {'error': text} when server responds with isError=True."""
    session_mock = _make_session_mock()
    content_item = MagicMock()
    content_item.text = "permission denied"
    call_result = MagicMock()
    call_result.isError = True
    call_result.content = [content_item]
    session_mock.call_tool = AsyncMock(return_value=call_result)

    with (
        patch("agentic_concierge.infrastructure.mcp.session.StdioServerParameters", MagicMock()),
        patch("agentic_concierge.infrastructure.mcp.session.stdio_client", side_effect=_noop_transport_cm),
        patch("agentic_concierge.infrastructure.mcp.session.ClientSession", side_effect=lambda r, w: _session_cm(session_mock)),
        patch("agentic_concierge.infrastructure.mcp.session._MCP_AVAILABLE", True),
    ):
        mgr = MCPSessionManager(_stdio_config("github"))
        await mgr.connect()
        result = await mgr.call_tool("mcp__github__do_thing", {})

    assert result == {"error": "permission denied"}


@pytest.mark.asyncio
async def test_call_tool_returns_empty_result_on_empty_content():
    """call_tool() returns {'result': ''} when server returns no content."""
    session_mock = _make_session_mock()
    call_result = MagicMock()
    call_result.isError = False
    call_result.content = []
    session_mock.call_tool = AsyncMock(return_value=call_result)

    with (
        patch("agentic_concierge.infrastructure.mcp.session.StdioServerParameters", MagicMock()),
        patch("agentic_concierge.infrastructure.mcp.session.stdio_client", side_effect=_noop_transport_cm),
        patch("agentic_concierge.infrastructure.mcp.session.ClientSession", side_effect=lambda r, w: _session_cm(session_mock)),
        patch("agentic_concierge.infrastructure.mcp.session._MCP_AVAILABLE", True),
    ):
        mgr = MCPSessionManager(_stdio_config("github"))
        await mgr.connect()
        result = await mgr.call_tool("mcp__github__noop", {})

    assert result == {"result": ""}
