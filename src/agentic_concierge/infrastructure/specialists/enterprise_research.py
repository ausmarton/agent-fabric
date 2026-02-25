"""Enterprise research specialist pack (P7-3).

Designed for the §4.3 use case from VISION.md: search Confluence, GitHub, Jira,
and similar enterprise sources via MCP-backed tools, then produce structured
reports with staleness and confidence annotations.

Unlike the base research pack, this pack:
- Includes a ``cross_run_search`` tool that queries the cross-run run index,
  enabling the agent to build on prior research without starting cold.
- Assumes MCP servers are wired via ``SpecialistConfig.mcp_servers`` in config;
  the pack itself only provides file/cross-run tools — enterprise-specific tools
  come from MCP sessions (``MCPAugmentedPack`` wraps this at registry time).
- Has a system prompt tailored for enterprise search: staleness/confidence
  notation, multi-source cross-referencing, and structured reports.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple

from agentic_concierge.infrastructure.tools.sandbox import SandboxPolicy
from agentic_concierge.infrastructure.tools.file_tools import read_text, write_text, list_tree
from agentic_concierge.infrastructure.tools.web_tools import web_search, fetch_url

from .base import BaseSpecialistPack
from .prompts import SYSTEM_PROMPT_ENTERPRISE_RESEARCH
from .tool_defs import (
    make_tool_def,
    make_finish_tool_def,
    READ_FILE_TOOL_DEF,
    WRITE_FILE_TOOL_DEF,
    LIST_FILES_TOOL_DEF,
)


_FINISH_TOOL_DEF = make_finish_tool_def(
    description=(
        "Call this when enterprise research is complete. Provide an executive summary, "
        "source attributions with confidence ratings ([HIGH]/[MEDIUM]/[LOW]/[STALE?]), "
        "staleness notes, and paths to the written report and artefact files."
    ),
    properties={
        "executive_summary": {
            "type": "string",
            "description": "High-level summary of findings with staleness/confidence overview.",
        },
        "key_findings": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Key findings, each annotated with confidence: "
                "[HIGH]/[MEDIUM]/[LOW]/[STALE?]/[UNVERIFIED]."
            ),
        },
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "Tool name or URL used."},
                    "content_summary": {"type": "string"},
                    "confidence": {
                        "type": "string",
                        "enum": ["HIGH", "MEDIUM", "LOW", "STALE?", "UNVERIFIED"],
                    },
                    "staleness_note": {"type": "string"},
                },
                "required": ["source", "content_summary", "confidence"],
            },
            "description": "All sources retrieved during research.",
        },
        "report_path": {
            "type": "string",
            "description": "Workspace-relative path to the written report file.",
        },
        "gaps_and_future_work": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Open questions, missing information, or recommended follow-up.",
        },
        "notes": {
            "type": "string",
            "description": "Caveats, reproducibility notes, or session metadata.",
        },
    },
    required=["executive_summary"],
)


def build_enterprise_research_pack(
    workspace_path: str,
    network_allowed: bool = False,
) -> BaseSpecialistPack:
    """Build the enterprise research specialist pack.

    Args:
        workspace_path: Path to the run-specific workspace directory.
        network_allowed: When True, web_search and fetch_url are included so the
            agent can supplement enterprise sources with public web research.

    The workspace root (two levels up from workspace_path) is used to search the
    cross-run index, enabling the agent to build on prior research results.
    """
    policy = SandboxPolicy(root=Path(workspace_path), network_allowed=network_allowed)

    # Derive the workspace root from the run workspace path.
    # Structure: {workspace_root}/runs/{run_id}/workspace → workspace_root = parent * 3
    workspace_root = str(Path(workspace_path).parent.parent.parent)

    tools: Dict[str, Tuple[Dict[str, Any], Any]] = {}

    # Cross-run memory: search prior research results before duplicating work.
    def _cross_run_search(query: str, limit: int = 5) -> dict:
        """Search the cross-run index for relevant prior run summaries."""
        try:
            from agentic_concierge.infrastructure.workspace.run_index import search_index
            results = search_index(workspace_root, query, limit=limit)
            return {
                "results": [
                    {
                        "run_id": entry.run_id,
                        "prompt": entry.prompt_prefix,
                        "summary": entry.summary,
                        "specialists": entry.specialist_ids,
                        "model": entry.model_name,
                    }
                    for entry in results
                ],
                "query": query,
                "count": len(results),
                "note": (
                    "These are summaries from prior runs. "
                    "Verify key claims with current tool calls."
                ),
            }
        except Exception as exc:  # noqa: BLE001
            return {"error": f"cross_run_search failed: {exc}", "query": query, "results": []}

    tools["cross_run_search"] = (
        make_tool_def(
            "cross_run_search",
            (
                "Search the cross-run memory index for relevant prior research results. "
                "Always call this first to avoid repeating previous work. "
                "Returns summaries of past runs whose prompts or summaries match the query."
            ),
            {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (keywords or a short phrase).",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default 5).",
                    },
                },
                "required": ["query"],
            },
        ),
        _cross_run_search,
    )

    # Web tools (only when network is allowed)
    if network_allowed:
        tools["web_search"] = (
            make_tool_def(
                "web_search",
                "Search the public web. Use for supplementing enterprise sources with external context.",
                {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query."},
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of results (default 8).",
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
                "Fetch the full text of a URL. Only URLs fetched here may be cited as sources.",
                {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to fetch."},
                    },
                    "required": ["url"],
                },
            ),
            lambda url: fetch_url(url),
        )

    # File tools
    tools["write_file"] = (
        WRITE_FILE_TOOL_DEF,
        lambda path, content: write_text(policy, path, content),
    )
    tools["read_file"] = (READ_FILE_TOOL_DEF, lambda path: read_text(policy, path))
    tools["list_files"] = (
        LIST_FILES_TOOL_DEF,
        lambda max_files=500: list_tree(policy, max_files=max_files),
    )

    return BaseSpecialistPack(
        specialist_id="enterprise_research",
        system_prompt=SYSTEM_PROMPT_ENTERPRISE_RESEARCH,
        tools=tools,
        finish_tool_def=_FINISH_TOOL_DEF,
    )
