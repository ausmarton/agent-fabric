"""Convert MCP tool definitions to OpenAI function-calling format."""

from __future__ import annotations

from typing import Any, Dict


def mcp_tool_to_openai_def(prefixed_name: str, tool: Any) -> Dict[str, Any]:
    """Wrap an MCP ``Tool`` object into an OpenAI function tool definition dict.

    Args:
        prefixed_name: Full prefixed name, e.g. ``mcp__github__create_issue``.
        tool: An MCP ``Tool`` object (has ``.name``, ``.description``, ``.inputSchema``).

    Returns:
        OpenAI-format tool definition dict with ``type: "function"``.
    """
    schema = tool.inputSchema
    if schema is None:
        schema = {"type": "object", "properties": {}, "required": []}
    return {
        "type": "function",
        "function": {
            "name": prefixed_name,
            "description": tool.description or "",
            "parameters": schema,
        },
    }
