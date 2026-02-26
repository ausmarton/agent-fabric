"""Tests for specialist packs (engineering, research): tool lists and finish_tool."""
from __future__ import annotations

import tempfile

import pytest
from agentic_concierge.infrastructure.specialists.engineering import build_engineering_pack
from agentic_concierge.infrastructure.specialists.research import build_research_pack


def test_engineering_pack_has_tools():
    with tempfile.TemporaryDirectory() as d:
        pack = build_engineering_pack(d, network_allowed=False)
        assert "shell" in pack.tool_names
        assert "read_file" in pack.tool_names
        assert "write_file" in pack.tool_names
        assert "list_files" in pack.tool_names


@pytest.mark.parametrize("network_allowed", [False, True])
def test_engineering_pack_tools_unchanged_by_network_flag(network_allowed):
    """Engineering has no conditional network tools; tool set must be identical
    regardless of network_allowed (unlike the research pack which omits web tools
    when network_allowed=False)."""
    with tempfile.TemporaryDirectory() as d:
        pack = build_engineering_pack(d, network_allowed=network_allowed)
        # All tools (including run_tests added in Phase 12) must always be present.
        assert set(pack.tool_names) == {"shell", "read_file", "write_file", "list_files", "run_tests"}


def test_research_pack_network_allowed_has_web_tools():
    with tempfile.TemporaryDirectory() as d:
        pack = build_research_pack(d, network_allowed=True)
        assert "web_search" in pack.tool_names
        assert "fetch_url" in pack.tool_names
        assert "write_file" in pack.tool_names


def test_research_pack_no_network_omits_web_tools():
    with tempfile.TemporaryDirectory() as d:
        pack = build_research_pack(d, network_allowed=False)
        assert "web_search" not in pack.tool_names
        assert "fetch_url" not in pack.tool_names
        assert "write_file" in pack.tool_names
        assert "read_file" in pack.tool_names
        assert "list_files" in pack.tool_names


@pytest.mark.parametrize("builder,network_allowed", [
    (build_engineering_pack, False),
    (build_research_pack, False),
])
def test_finish_tool_in_definitions(builder, network_allowed):
    """finish_task must appear in tool_definitions so the LLM knows to call it."""
    with tempfile.TemporaryDirectory() as d:
        pack = builder(d, network_allowed=network_allowed)
        names = [t["function"]["name"] for t in pack.tool_definitions]
        assert "finish_task" in names
        assert pack.finish_tool_name == "finish_task"


@pytest.mark.parametrize("builder,network_allowed", [
    (build_engineering_pack, False),
    (build_research_pack, True),
])
def test_tool_definitions_are_valid_openai_format(builder, network_allowed):
    """Every tool definition must have type=function and a function.name."""
    with tempfile.TemporaryDirectory() as d:
        pack = builder(d, network_allowed=network_allowed)
        for td in pack.tool_definitions:
            assert td.get("type") == "function"
            assert "function" in td
            assert "name" in td["function"]
            assert "parameters" in td["function"]
