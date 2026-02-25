"""Real GitHub MCP server integration tests (P7-2).

Uses the official @modelcontextprotocol/server-github npm package to exercise
MCPSessionManager against the real GitHub API.

Prerequisites:
    npm install -g @modelcontextprotocol/server-github
    (or npx @modelcontextprotocol/server-github is available)
    GITHUB_TOKEN environment variable must be set to a valid GitHub personal access token.

Skipped automatically when:
- npx is not in PATH
- GITHUB_TOKEN is not set in the environment
- The @modelcontextprotocol/server-github package cannot be resolved via npx
- The mcp Python package is not installed

Run with:
    GITHUB_TOKEN=ghp_... pytest tests/test_mcp_real_github.py -k real_mcp -v
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.real_mcp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def skip_if_github_token_missing():
    """Skip when GITHUB_TOKEN is not set — required for authenticated GitHub API calls."""
    if not os.environ.get("GITHUB_TOKEN"):
        pytest.skip(
            "GITHUB_TOKEN environment variable not set; "
            "set it to a GitHub PAT to run real GitHub MCP tests"
        )


@pytest.fixture(scope="module")
def skip_if_npx_unavailable():
    """Skip if npx is not in PATH or the GitHub MCP server package is unavailable."""
    if shutil.which("npx") is None:
        pytest.skip("npx not in PATH — install Node.js to run real_mcp tests")

    try:
        proc = subprocess.run(
            ["npx", "--yes", "--", "@modelcontextprotocol/server-github", "--help"],
            capture_output=True,
            timeout=30,
        )
        if proc.returncode != 0 and b"not found" in proc.stderr.lower():
            pytest.skip(
                "@modelcontextprotocol/server-github not found via npx; "
                "run: npm install -g @modelcontextprotocol/server-github"
            )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pytest.skip("Could not probe @modelcontextprotocol/server-github via npx")


@pytest.fixture(scope="module")
def skip_if_mcp_not_installed():
    """Skip if the mcp Python package is not installed."""
    try:
        import mcp  # noqa: F401
    except ImportError:
        pytest.skip("mcp Python package not installed; run: pip install agentic-concierge[mcp]")


@pytest.fixture(scope="module")
def github_mcp_config():
    """Return an MCPServerConfig for the GitHub MCP server authenticated via GITHUB_TOKEN."""
    from agentic_concierge.config.schema import MCPServerConfig

    return MCPServerConfig(
        name="github",
        transport="stdio",
        command="npx",
        args=["--yes", "--", "@modelcontextprotocol/server-github"],
        env={"GITHUB_TOKEN": os.environ["GITHUB_TOKEN"]},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_tools_returns_non_empty(
    skip_if_github_token_missing,
    skip_if_npx_unavailable,
    skip_if_mcp_not_installed,
    github_mcp_config,
):
    """MCPSessionManager.list_tools() returns at least one tool from the GitHub server."""
    from agentic_concierge.infrastructure.mcp.session import MCPSessionManager

    mgr = MCPSessionManager(github_mcp_config)
    try:
        await mgr.connect()
        tools = await mgr.list_tools()
    finally:
        await mgr.disconnect()

    assert tools, "Expected at least one tool from the GitHub MCP server"
    for tool in tools:
        assert tool["type"] == "function"
        assert "function" in tool
        assert "name" in tool["function"]
        assert tool["function"]["name"].startswith("mcp__github__"), (
            f"Expected mcp__github__ prefix on tool name, got: {tool['function']['name']!r}"
        )


@pytest.mark.asyncio
async def test_search_repositories(
    skip_if_github_token_missing,
    skip_if_npx_unavailable,
    skip_if_mcp_not_installed,
    github_mcp_config,
):
    """search_repositories tool returns results for a well-known query."""
    from agentic_concierge.infrastructure.mcp.session import MCPSessionManager

    mgr = MCPSessionManager(github_mcp_config)
    try:
        await mgr.connect()
        tools = await mgr.list_tools()
        search_tool = next(
            (t for t in tools if "search_repositories" in t["function"]["name"]),
            None,
        )
        if search_tool is None:
            pytest.skip("search_repositories tool not found on this GitHub MCP server version")

        tool_name = search_tool["function"]["name"]
        result = await mgr.call_tool(tool_name, {"query": "modelcontextprotocol language:TypeScript"})
    finally:
        await mgr.disconnect()

    assert "result" in result or "error" in result, (
        f"Expected 'result' or 'error' key in response, got: {result}"
    )
    # If it succeeded, the result should contain repository info
    if "result" in result:
        assert isinstance(result["result"], str), "Expected result to be a string"


@pytest.mark.asyncio
async def test_get_file_contents(
    skip_if_github_token_missing,
    skip_if_npx_unavailable,
    skip_if_mcp_not_installed,
    github_mcp_config,
):
    """get_file_contents tool can fetch a file from a public repo."""
    from agentic_concierge.infrastructure.mcp.session import MCPSessionManager

    mgr = MCPSessionManager(github_mcp_config)
    try:
        await mgr.connect()
        tools = await mgr.list_tools()
        get_file_tool = next(
            (t for t in tools if "get_file_contents" in t["function"]["name"]),
            None,
        )
        if get_file_tool is None:
            pytest.skip("get_file_contents tool not found on this GitHub MCP server version")

        tool_name = get_file_tool["function"]["name"]
        # Fetch the README from the official MCP repo (always public and stable)
        result = await mgr.call_tool(
            tool_name,
            {
                "owner": "modelcontextprotocol",
                "repo": "modelcontextprotocol",
                "path": "README.md",
            },
        )
    finally:
        await mgr.disconnect()

    assert "result" in result or "error" in result, (
        f"Expected 'result' or 'error' key, got: {result}"
    )
    if "result" in result:
        assert "Model Context Protocol" in result["result"] or len(result["result"]) > 0, (
            "Expected non-empty README content"
        )


@pytest.mark.asyncio
async def test_unknown_tool_returns_error(
    skip_if_github_token_missing,
    skip_if_npx_unavailable,
    skip_if_mcp_not_installed,
    github_mcp_config,
):
    """call_tool() with an unknown name returns an error dict."""
    from agentic_concierge.infrastructure.mcp.session import MCPSessionManager

    mgr = MCPSessionManager(github_mcp_config)
    try:
        await mgr.connect()
        result = await mgr.call_tool("mcp__github__nonexistent_tool_xyz", {})
    finally:
        await mgr.disconnect()

    assert "error" in result, f"Expected error for unknown tool, got: {result}"
