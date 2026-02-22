"""Tests that tool-loop prompt templates format correctly (brace escaping)."""
from __future__ import annotations

from agent_fabric.infrastructure.specialists.prompts import (
    TOOL_LOOP_ENGINEERING,
    TOOL_LOOP_RESEARCH,
)


def test_engineering_tool_prompt_formats():
    out = TOOL_LOOP_ENGINEERING.format(tool_names="shell, read_file, write_file, list_files")
    assert "shell, read_file, write_file, list_files" in out
    assert '"action": "tool"' in out
    assert '"action": "final"' in out
    assert "{ ... }" in out or "{...}" in out or "..." in out


def test_research_tool_prompt_formats():
    out = TOOL_LOOP_RESEARCH.format(tool_names="web_search, fetch_url, write_file, read_file, list_files")
    assert "web_search" in out
    assert '"action": "final"' in out
    assert "deliverables" in out
