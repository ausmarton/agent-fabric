"""Shared tool-definition helpers for specialist packs.

All packs import from here instead of defining their own ``_tool()`` helper or
duplicating common file-tool definitions.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def make_tool_def(
    name: str,
    description: str,
    parameters: Dict[str, Any],
) -> Dict[str, Any]:
    """Build an OpenAI function tool definition dict."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }


def make_finish_tool_def(
    description: str,
    properties: Dict[str, Any],
    required: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Build a ``finish_task`` tool definition.

    Args:
        description: Human-readable instruction for when to call finish_task.
        properties: JSON Schema property definitions for the tool arguments.
        required: Required property names (defaults to empty list).
    """
    return make_tool_def(
        name="finish_task",
        description=description,
        parameters={
            "type": "object",
            "properties": properties,
            "required": required or [],
        },
    )


# ---------------------------------------------------------------------------
# Shared file-tool definitions (used by both engineering and research packs)
# ---------------------------------------------------------------------------

READ_FILE_TOOL_DEF = make_tool_def(
    "read_file",
    "Read the UTF-8 text content of a file in the workspace.",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path inside the workspace."},
        },
        "required": ["path"],
    },
)

WRITE_FILE_TOOL_DEF = make_tool_def(
    "write_file",
    "Write (or overwrite) a file in the workspace, creating parent directories as needed.",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path inside the workspace."},
            "content": {"type": "string", "description": "File content as a UTF-8 string."},
        },
        "required": ["path", "content"],
    },
)

LIST_FILES_TOOL_DEF = make_tool_def(
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
)
