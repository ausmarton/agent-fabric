"""Research specialist pack: web_search, fetch_url (gated), write_file, read_file, list_files, finish_task."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple

from agent_fabric.infrastructure.tools.sandbox import SandboxPolicy
from agent_fabric.infrastructure.tools.file_tools import read_text, write_text, list_tree
from agent_fabric.infrastructure.tools.web_tools import web_search, fetch_url

from .base import BaseSpecialistPack
from .prompts import SYSTEM_PROMPT_RESEARCH


def _tool(name: str, description: str, parameters: Dict[str, Any]):
    """Convenience: build an OpenAI function tool definition."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }


_FINISH_TOOL_DEF = _tool(
    name="finish_task",
    description=(
        "Call this when research is complete. Provide your executive summary, key "
        "findings, citations for all fetched URLs, paths to artefact files in the "
        "workspace, and any gaps or future work."
    ),
    parameters={
        "type": "object",
        "properties": {
            "executive_summary": {
                "type": "string",
                "description": "High-level summary of findings.",
            },
            "key_findings": {
                "type": "array",
                "items": {"type": "string"},
                "description": "The most important findings, as a list.",
            },
            "citations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "fetched_at": {"type": "string"},
                        "claim": {"type": "string", "description": "What this source supports."},
                    },
                    "required": ["url", "claim"],
                },
                "description": "Only URLs actually fetched via fetch_url.",
            },
            "evidence_table_path": {
                "type": "string",
                "description": "Workspace-relative path to the evidence table file.",
            },
            "screening_log_path": {
                "type": "string",
                "description": "Workspace-relative path to the screening log file.",
            },
            "bibliography_path": {
                "type": "string",
                "description": "Workspace-relative path to the bibliography file.",
            },
            "gaps_and_future_work": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Open questions or areas for further research.",
            },
            "notes": {
                "type": "string",
                "description": "How to reproduce searches, caveats, etc.",
            },
        },
        "required": ["executive_summary"],
    },
)


def build_research_pack(workspace_path: str, network_allowed: bool = False) -> BaseSpecialistPack:
    """Build the research specialist pack.

    When ``network_allowed`` is ``False``, ``web_search`` and ``fetch_url`` are
    omitted from the tool list so the LLM cannot try to use them.
    """
    policy = SandboxPolicy(root=Path(workspace_path), network_allowed=network_allowed)

    tools: Dict[str, Tuple[Dict[str, Any], Any]] = {}

    if network_allowed:
        tools["web_search"] = (
            _tool(
                "web_search",
                "Search the web and return a list of results (title, URL, snippet).",
                {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query string."},
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of results to return (default 8).",
                        },
                    },
                    "required": ["query"],
                },
            ),
            lambda query, max_results=8: web_search(query, max_results=max_results),
        )
        tools["fetch_url"] = (
            _tool(
                "fetch_url",
                "Fetch the full text content of a URL. Only URLs fetched here may be cited.",
                {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "The URL to fetch."},
                    },
                    "required": ["url"],
                },
            ),
            lambda url: fetch_url(url),
        )

    tools["write_file"] = (
        _tool(
            "write_file",
            "Write (or overwrite) a file in the workspace.",
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path inside the workspace."},
                    "content": {"type": "string", "description": "File content as a UTF-8 string."},
                },
                "required": ["path", "content"],
            },
        ),
        lambda path, content: write_text(policy, path, content),
    )
    tools["read_file"] = (
        _tool(
            "read_file",
            "Read the UTF-8 text content of a file in the workspace.",
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path inside the workspace."},
                },
                "required": ["path"],
            },
        ),
        lambda path: read_text(policy, path),
    )
    tools["list_files"] = (
        _tool(
            "list_files",
            "List all files currently in the workspace.",
            {
                "type": "object",
                "properties": {
                    "max_files": {
                        "type": "integer",
                        "description": "Maximum number of files to return (default 500).",
                    },
                },
                "required": [],
            },
        ),
        lambda max_files=500: list_tree(policy, max_files=max_files),
    )

    return BaseSpecialistPack(
        specialist_id="research",
        system_prompt=SYSTEM_PROMPT_RESEARCH,
        tools=tools,
        finish_tool_def=_FINISH_TOOL_DEF,
    )
