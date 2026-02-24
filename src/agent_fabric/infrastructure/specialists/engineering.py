"""Engineering specialist pack: shell, read_file, write_file, list_files, finish_task."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple

from agent_fabric.infrastructure.tools.sandbox import SandboxPolicy
from agent_fabric.infrastructure.tools.file_tools import read_text, write_text, list_tree
from agent_fabric.infrastructure.tools.shell_tools import run_shell

from .base import BaseSpecialistPack
from .prompts import SYSTEM_PROMPT_ENGINEERING


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
        "Call this when the task is complete. Provide a clear summary of what was "
        "accomplished, list any artefact file paths, and note any remaining steps "
        "(e.g. deployment commands that require human approval)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "What was accomplished (be specific).",
            },
            "artifacts": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Relative paths of files created or modified.",
            },
            "next_steps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Any remaining steps, especially ones needing human approval.",
            },
            "notes": {
                "type": "string",
                "description": "Caveats, test commands, or anything useful to know.",
            },
        },
        "required": ["summary"],
    },
)


def build_engineering_pack(workspace_path: str, network_allowed: bool = False) -> BaseSpecialistPack:
    """Build the engineering specialist pack for the given workspace.

    ``network_allowed`` is unused for engineering (shell commands may access the
    network freely; the parameter exists for API consistency with the registry).
    The sandbox restricts the *file system* to ``workspace_path``; shell commands
    are limited to an allowlist.
    """
    policy = SandboxPolicy(root=Path(workspace_path), network_allowed=True)

    tools: Dict[str, Tuple[Dict[str, Any], Any]] = {
        "shell": (
            _tool(
                "shell",
                "Run a shell command inside the sandbox workspace. Use for compiling, "
                "testing, running scripts, git operations, etc.",
                {
                    "type": "object",
                    "properties": {
                        "cmd": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Command and arguments as a list, e.g. [\"pytest\", \"-v\"].",
                        },
                        "timeout_s": {
                            "type": "integer",
                            "description": "Timeout in seconds (default 120).",
                        },
                    },
                    "required": ["cmd"],
                },
            ),
            lambda cmd, timeout_s=120: run_shell(policy, cmd, timeout_s=timeout_s),
        ),
        "read_file": (
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
        ),
        "write_file": (
            _tool(
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
            ),
            lambda path, content: write_text(policy, path, content),
        ),
        "list_files": (
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
        ),
    }

    return BaseSpecialistPack(
        specialist_id="engineering",
        system_prompt=SYSTEM_PROMPT_ENGINEERING,
        tools=tools,
        finish_tool_def=_FINISH_TOOL_DEF,
    )
