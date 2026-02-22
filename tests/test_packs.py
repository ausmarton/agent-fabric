"""Tests for specialist packs (engineering, research) and tool lists."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from agent_fabric.infrastructure.specialists.engineering import build_engineering_pack
from agent_fabric.infrastructure.specialists.research import build_research_pack


def test_engineering_pack_has_tools():
    with tempfile.TemporaryDirectory() as d:
        pack = build_engineering_pack(d, _network_allowed=False)
        assert "shell" in pack.tool_names
        assert "read_file" in pack.tool_names
        assert "write_file" in pack.tool_names
        assert "list_files" in pack.tool_names


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
