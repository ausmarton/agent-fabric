"""Engineering specialist pack: shell, read_file, write_file, list_files, finish_task."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple

from agent_fabric.infrastructure.tools.sandbox import SandboxPolicy
from agent_fabric.infrastructure.tools.file_tools import read_text, write_text, list_tree
from agent_fabric.infrastructure.tools.shell_tools import run_shell

from .base import BaseSpecialistPack
from .prompts import SYSTEM_PROMPT_ENGINEERING
from agent_fabric.config.constants import SHELL_DEFAULT_TIMEOUT_S
from .tool_defs import (
    make_tool_def,
    make_finish_tool_def,
    READ_FILE_TOOL_DEF,
    WRITE_FILE_TOOL_DEF,
    LIST_FILES_TOOL_DEF,
)


_FINISH_TOOL_DEF = make_finish_tool_def(
    description=(
        "Call this when the task is complete. Provide a clear summary of what was "
        "accomplished, list any artefact file paths, and note any remaining steps "
        "(e.g. deployment commands that require human approval)."
    ),
    properties={
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
    required=["summary"],
)


def build_engineering_pack(workspace_path: str, network_allowed: bool = False) -> BaseSpecialistPack:
    """Build the engineering specialist pack for the given workspace.

    ``network_allowed`` is forwarded to ``SandboxPolicy`` to record the caller's
    intent.  Note: the shell sandbox does not currently enforce network blocking
    (shell commands run as subprocesses and cannot be network-isolated without OS
    controls such as namespaces).  This flag is stored so future enforcement can
    be added without a signature change.  The sandbox does restrict the *file
    system* to ``workspace_path``; shell commands are limited to an allowlist.
    """
    policy = SandboxPolicy(root=Path(workspace_path), network_allowed=network_allowed)

    tools: Dict[str, Tuple[Dict[str, Any], Any]] = {
        "shell": (
            make_tool_def(
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
            lambda cmd, timeout_s=SHELL_DEFAULT_TIMEOUT_S: run_shell(policy, cmd, timeout_s=timeout_s),
        ),
        "read_file": (READ_FILE_TOOL_DEF, lambda path: read_text(policy, path)),
        "write_file": (WRITE_FILE_TOOL_DEF, lambda path, content: write_text(policy, path, content)),
        "list_files": (LIST_FILES_TOOL_DEF, lambda max_files=500: list_tree(policy, max_files=max_files)),
    }

    return BaseSpecialistPack(
        specialist_id="engineering",
        system_prompt=SYSTEM_PROMPT_ENGINEERING,
        tools=tools,
        finish_tool_def=_FINISH_TOOL_DEF,
    )
