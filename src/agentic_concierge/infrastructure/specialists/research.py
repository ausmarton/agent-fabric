"""Research specialist pack: web_search, fetch_url (gated), write_file, read_file, list_files, finish_task."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple

from agentic_concierge.infrastructure.tools.sandbox import SandboxPolicy
from agentic_concierge.infrastructure.tools.file_tools import read_text, write_text, list_tree
from agentic_concierge.infrastructure.tools.web_tools import web_search, fetch_url

from .base import BaseSpecialistPack
from .prompts import SYSTEM_PROMPT_RESEARCH
from .tool_defs import (
    make_tool_def,
    make_finish_tool_def,
    READ_FILE_TOOL_DEF,
    WRITE_FILE_TOOL_DEF,
    LIST_FILES_TOOL_DEF,
)


_FINISH_TOOL_DEF = make_finish_tool_def(
    description=(
        "Call this when research is complete. Provide your executive summary, key "
        "findings, citations for all fetched URLs, paths to artefact files in the "
        "workspace, and any gaps or future work."
    ),
    properties={
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
    required=["executive_summary"],
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
            make_tool_def(
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
            make_tool_def(
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

    tools["write_file"] = (WRITE_FILE_TOOL_DEF, lambda path, content: write_text(policy, path, content))
    tools["read_file"] = (READ_FILE_TOOL_DEF, lambda path: read_text(policy, path))
    tools["list_files"] = (LIST_FILES_TOOL_DEF, lambda max_files=500: list_tree(policy, max_files=max_files))

    return BaseSpecialistPack(
        specialist_id="research",
        system_prompt=SYSTEM_PROMPT_RESEARCH,
        tools=tools,
        finish_tool_def=_FINISH_TOOL_DEF,
    )
