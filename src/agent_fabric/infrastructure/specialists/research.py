"""Research specialist pack: web_search, fetch_url, write_file, read_file, list_files."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from agent_fabric.infrastructure.tools.sandbox import SandboxPolicy
from agent_fabric.infrastructure.tools.file_tools import read_text, write_text, list_tree
from agent_fabric.infrastructure.tools.web_tools import web_search, fetch_url

from .base import BaseSpecialistPack
from .prompts import TOOL_LOOP_RESEARCH

SYSTEM_PROMPT = """You are an autonomous research team performing rigorous literature review.
Quality > speed. Be skeptical. Prefer primary sources. Always cite sources.

Hard rules:
- Never invent citations. Only cite URLs you actually fetched.
- Keep a screening log: include inclusion/exclusion reasons.
- Separate 'what the source says' from your inference.
- Flag uncertainty and contradictory evidence."""


def build_research_pack(workspace_path: str, network_allowed: bool = False) -> BaseSpecialistPack:
    policy = SandboxPolicy(root=Path(workspace_path), network_allowed=network_allowed)
    tools: Dict[str, tuple[Dict[str, Any], Any]] = {}
    if network_allowed:
        tools["web_search"] = (
            {"type": "object", "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["query"]},
            lambda query, max_results=8: web_search(query, max_results=max_results),
        )
        tools["fetch_url"] = (
            {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
            lambda url: fetch_url(url),
        )
    tools["write_file"] = (
        {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
        lambda path, content: write_text(policy, path, content),
    )
    tools["read_file"] = (
        {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        lambda path: read_text(policy, path),
    )
    tools["list_files"] = (
        {"type": "object", "properties": {"max_files": {"type": "integer"}}, "required": []},
        lambda max_files=500: list_tree(policy, max_files=max_files),
    )
    return BaseSpecialistPack(
        specialist_id="research",
        system_prompt=SYSTEM_PROMPT,
        tool_loop_prompt_template=TOOL_LOOP_RESEARCH,
        tools=tools,
    )
