"""Tests for MCPAugmentedPack.

All MCP sessions are mocked — no real MCP server required.
"""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_fabric.infrastructure.mcp.augmented_pack import MCPAugmentedPack


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeInnerPack:
    """Minimal inner SpecialistPack for testing."""
    specialist_id = "engineering"
    system_prompt = "You are an engineer."
    finish_tool_name = "finish_task"
    finish_required_fields = ["summary"]
    tool_definitions = [{"type": "function", "function": {"name": "shell"}}]

    async def execute_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if name == "shell":
            return {"stdout": "ok"}
        return {"error": f"Unknown tool: {name!r}"}


def _make_session(name: str, tool_names: List[str] | None = None) -> MagicMock:
    """Return a mock MCPSessionManager."""
    session = MagicMock()
    session.name = name
    session.connect = AsyncMock()
    session.disconnect = AsyncMock()
    tool_defs = [
        {"type": "function", "function": {"name": f"mcp__{name}__{t}"}}
        for t in (tool_names or [])
    ]
    session.list_tools = AsyncMock(return_value=tool_defs)
    session.call_tool = AsyncMock(return_value={"result": "mcp_result"})
    session.owns_tool = lambda n: n.startswith(f"mcp__{name}__")
    return session


# ---------------------------------------------------------------------------
# aopen tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_aopen_connects_all_sessions():
    """aopen() calls connect() on every session."""
    s1 = _make_session("github", ["create_issue"])
    s2 = _make_session("jira", ["create_ticket"])
    pack = MCPAugmentedPack(_FakeInnerPack(), [s1, s2])
    await pack.aopen()
    s1.connect.assert_awaited_once()
    s2.connect.assert_awaited_once()


@pytest.mark.asyncio
async def test_aopen_merges_mcp_tool_defs():
    """After aopen(), tool_definitions includes inner tools AND MCP tools."""
    s1 = _make_session("github", ["create_issue"])
    pack = MCPAugmentedPack(_FakeInnerPack(), [s1])
    await pack.aopen()
    names = [td["function"]["name"] for td in pack.tool_definitions]
    assert "shell" in names
    assert "mcp__github__create_issue" in names


# ---------------------------------------------------------------------------
# aclose tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_aclose_disconnects_all_sessions():
    """aclose() calls disconnect() on every session."""
    s1 = _make_session("github")
    s2 = _make_session("jira")
    pack = MCPAugmentedPack(_FakeInnerPack(), [s1, s2])
    await pack.aopen()
    await pack.aclose()
    s1.disconnect.assert_awaited_once()
    s2.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_aclose_ignores_individual_failures():
    """aclose() completes even when one session's disconnect raises."""
    s1 = _make_session("github")
    s1.disconnect = AsyncMock(side_effect=RuntimeError("disconnect failed"))
    s2 = _make_session("jira")
    pack = MCPAugmentedPack(_FakeInnerPack(), [s1, s2])
    # Should not raise.
    await pack.aclose()
    s2.disconnect.assert_awaited_once()


# ---------------------------------------------------------------------------
# tool_definitions before aopen
# ---------------------------------------------------------------------------

def test_tool_definitions_before_aopen_contains_only_inner_tools():
    """Before aopen(), tool_definitions only has the inner pack's tools."""
    s1 = _make_session("github", ["create_issue"])
    pack = MCPAugmentedPack(_FakeInnerPack(), [s1])
    names = [td["function"]["name"] for td in pack.tool_definitions]
    assert "shell" in names
    assert "mcp__github__create_issue" not in names


# ---------------------------------------------------------------------------
# execute_tool dispatch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_tool_dispatches_to_owning_session():
    """execute_tool() routes mcp-prefixed tools to the owning session."""
    s1 = _make_session("github", ["create_issue"])
    s1.call_tool = AsyncMock(return_value={"result": "created"})
    pack = MCPAugmentedPack(_FakeInnerPack(), [s1])
    await pack.aopen()
    result = await pack.execute_tool("mcp__github__create_issue", {"title": "bug"})
    s1.call_tool.assert_awaited_once_with("mcp__github__create_issue", {"title": "bug"})
    assert result == {"result": "created"}


@pytest.mark.asyncio
async def test_execute_tool_falls_through_to_inner_pack_for_native_tool():
    """execute_tool() delegates non-MCP tool names to the inner pack."""
    s1 = _make_session("github", ["create_issue"])
    pack = MCPAugmentedPack(_FakeInnerPack(), [s1])
    await pack.aopen()
    result = await pack.execute_tool("shell", {"cmd": "ls"})
    assert result == {"stdout": "ok"}


@pytest.mark.asyncio
async def test_execute_tool_unknown_tool_returns_error_from_inner():
    """execute_tool() returns error dict for a tool not owned by any session or inner pack."""
    s1 = _make_session("github")
    pack = MCPAugmentedPack(_FakeInnerPack(), [s1])
    await pack.aopen()
    result = await pack.execute_tool("totally_unknown_tool", {})
    assert "error" in result


# ---------------------------------------------------------------------------
# Protocol property pass-through
# ---------------------------------------------------------------------------

def test_specialist_pack_properties_forwarded():
    """specialist_id, system_prompt, finish_tool_name, finish_required_fields pass through."""
    inner = _FakeInnerPack()
    pack = MCPAugmentedPack(inner, [])
    assert pack.specialist_id == "engineering"
    assert pack.system_prompt == "You are an engineer."
    assert pack.finish_tool_name == "finish_task"
    assert pack.finish_required_fields == ["summary"]
