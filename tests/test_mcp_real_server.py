"""Real MCP server smoke test (P6-2).

Uses the official @modelcontextprotocol/server-filesystem npm package as a
real stdio MCP server to exercise MCPSessionManager end-to-end without any
mocking of the transport layer.

Prerequisites:
    npm install -g @modelcontextprotocol/server-filesystem
    (or npx @modelcontextprotocol/server-filesystem is available)

Skipped automatically when:
- npx is not in PATH
- The @modelcontextprotocol/server-filesystem package cannot be resolved via npx
- The mcp Python package is not installed

Run with:
    pytest tests/test_mcp_real_server.py -k real_mcp -v
"""
from __future__ import annotations

import shutil
import subprocess
import sys

import pytest

pytestmark = pytest.mark.real_mcp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def skip_if_npx_unavailable():
    """Skip the test module if npx is not in PATH or the filesystem server is unavailable."""
    if shutil.which("npx") is None:
        pytest.skip("npx not in PATH — install Node.js to run real_mcp tests")

    # Quick probe: does npx know about the filesystem server package?
    try:
        proc = subprocess.run(
            ["npx", "--yes", "--", "@modelcontextprotocol/server-filesystem", "--help"],
            capture_output=True,
            timeout=30,
        )
        # If it exits non-zero and there's an error about not found, skip.
        if proc.returncode != 0 and b"not found" in proc.stderr.lower():
            pytest.skip(
                "@modelcontextprotocol/server-filesystem not found via npx; "
                "run: npm install -g @modelcontextprotocol/server-filesystem"
            )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pytest.skip("Could not probe @modelcontextprotocol/server-filesystem via npx")


@pytest.fixture(scope="module")
def skip_if_mcp_not_installed():
    """Skip if the mcp Python package is not installed."""
    try:
        import mcp  # noqa: F401
    except ImportError:
        pytest.skip("mcp Python package not installed; run: pip install agent-fabric[mcp]")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fs_server_config(root_dir: str):
    """Build an MCPServerConfig pointing the filesystem server at root_dir."""
    from agent_fabric.config.schema import MCPServerConfig

    return MCPServerConfig(
        name="fs",
        transport="stdio",
        command="npx",
        args=["--yes", "--", "@modelcontextprotocol/server-filesystem", root_dir],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_tools_returns_non_empty(
    tmp_path,
    skip_if_npx_unavailable,
    skip_if_mcp_not_installed,
):
    """MCPSessionManager.list_tools() returns at least one OpenAI-format tool def."""
    from agent_fabric.infrastructure.mcp.session import MCPSessionManager

    cfg = _make_fs_server_config(str(tmp_path))
    mgr = MCPSessionManager(cfg)
    try:
        await mgr.connect()
        tools = await mgr.list_tools()
    finally:
        await mgr.disconnect()

    assert tools, "Expected at least one tool from the filesystem MCP server"
    # Each tool should be an OpenAI-format function definition
    for tool in tools:
        assert tool["type"] == "function"
        assert "function" in tool
        assert "name" in tool["function"]
        # Tool names must be prefixed
        assert tool["function"]["name"].startswith("mcp__fs__"), (
            f"Expected mcp__fs__ prefix on tool name, got: {tool['function']['name']!r}"
        )


@pytest.mark.asyncio
async def test_owns_tool_prefix(
    tmp_path,
    skip_if_npx_unavailable,
    skip_if_mcp_not_installed,
):
    """MCPSessionManager.owns_tool() correctly identifies prefixed names."""
    from agent_fabric.infrastructure.mcp.session import MCPSessionManager

    cfg = _make_fs_server_config(str(tmp_path))
    mgr = MCPSessionManager(cfg)
    try:
        await mgr.connect()
        tools = await mgr.list_tools()
    finally:
        await mgr.disconnect()

    for tool in tools:
        name = tool["function"]["name"]
        assert mgr.owns_tool(name), f"owns_tool() returned False for {name!r}"
    assert not mgr.owns_tool("shell")
    assert not mgr.owns_tool("mcp__other__tool")


@pytest.mark.asyncio
async def test_read_file_via_call_tool(
    tmp_path,
    skip_if_npx_unavailable,
    skip_if_mcp_not_installed,
):
    """MCPSessionManager.call_tool() can read a file via the filesystem server."""
    # Write a file in the tmp workspace that the MCP server will read
    sentinel_file = tmp_path / "hello.txt"
    sentinel_file.write_text("hello from agent-fabric\n")

    from agent_fabric.infrastructure.mcp.session import MCPSessionManager

    cfg = _make_fs_server_config(str(tmp_path))
    mgr = MCPSessionManager(cfg)
    try:
        await mgr.connect()

        # Discover the read_file tool name (it may vary slightly between server versions)
        tools = await mgr.list_tools()
        read_tool = next(
            (t for t in tools if "read" in t["function"]["name"].lower()),
            None,
        )
        if read_tool is None:
            pytest.skip("No read tool found on the filesystem MCP server")

        tool_name = read_tool["function"]["name"]
        result = await mgr.call_tool(tool_name, {"path": str(sentinel_file)})
    finally:
        await mgr.disconnect()

    assert "result" in result, f"Expected 'result' key, got: {result}"
    assert "hello from agent-fabric" in result["result"], (
        f"Expected file content in result, got: {result['result']!r}"
    )


@pytest.mark.asyncio
async def test_unknown_tool_returns_error(
    tmp_path,
    skip_if_npx_unavailable,
    skip_if_mcp_not_installed,
):
    """call_tool() with an unknown bare name returns an error dict (isError=True)."""
    from agent_fabric.infrastructure.mcp.session import MCPSessionManager

    cfg = _make_fs_server_config(str(tmp_path))
    mgr = MCPSessionManager(cfg)
    try:
        await mgr.connect()
        result = await mgr.call_tool("mcp__fs__nonexistent_tool_xyz", {})
    finally:
        await mgr.disconnect()

    # The server returns isError=True for unknown tools
    assert "error" in result, f"Expected error for unknown tool, got: {result}"


@pytest.mark.asyncio
async def test_reconnect_after_disconnect(
    tmp_path,
    skip_if_npx_unavailable,
    skip_if_mcp_not_installed,
):
    """MCPSessionManager can be reconnected after disconnecting."""
    from agent_fabric.infrastructure.mcp.session import MCPSessionManager

    cfg = _make_fs_server_config(str(tmp_path))
    mgr = MCPSessionManager(cfg)

    # First connection
    await mgr.connect()
    tools_first = await mgr.list_tools()
    await mgr.disconnect()

    # Second connection — should work cleanly
    await mgr.connect()
    tools_second = await mgr.list_tools()
    await mgr.disconnect()

    assert len(tools_first) == len(tools_second), (
        "Tool count changed between connections"
    )
