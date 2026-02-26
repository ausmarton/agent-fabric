"""Engineering specialist pack: shell, read_file, write_file, list_files, run_tests, finish_task."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from agentic_concierge.infrastructure.tools.sandbox import SandboxPolicy
from agentic_concierge.infrastructure.tools.file_tools import read_text, write_text, list_tree
from agentic_concierge.infrastructure.tools.shell_tools import run_shell
from agentic_concierge.infrastructure.tools.test_runner import run_tests

from .base import BaseSpecialistPack
from .prompts import SYSTEM_PROMPT_ENGINEERING
from agentic_concierge.config.constants import SHELL_DEFAULT_TIMEOUT_S
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
        "(e.g. deployment commands that require human approval). "
        "You MUST call run_tests first and set tests_verified=true."
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
        "tests_verified": {
            "type": "boolean",
            "description": (
                "Set to true only after run_tests confirms all tests pass. "
                "Do not call finish_task with false — fix failures first."
            ),
        },
    },
    required=["summary", "tests_verified"],
)


class EngineeringSpecialistPack(BaseSpecialistPack):
    """Engineering specialist pack with a quality gate enforcing test verification."""

    def validate_finish_payload(self, payload: dict) -> Optional[str]:
        """Reject finish_task when tests_verified is explicitly False.

        The LLM must call run_tests, confirm all tests pass, and then set
        tests_verified=true.  Calling finish_task with tests_verified=false
        is treated as a quality gate failure and the LLM is asked to retry.
        """
        if payload.get("tests_verified") is False:
            return (
                "tests_verified is False. Run run_tests to check the test suite. "
                "Fix any failures, then call finish_task with tests_verified=true."
            )
        return None


def build_engineering_pack(workspace_path: str, network_allowed: bool = False) -> EngineeringSpecialistPack:
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
        "run_tests": (
            make_tool_def(
                "run_tests",
                "Run the project's test suite and return pass/fail status. "
                "Call this before finish_task to verify correctness.",
                {
                    "type": "object",
                    "properties": {
                        "framework": {
                            "type": "string",
                            "description": (
                                "Test framework: 'auto' (detect), 'pytest', 'cargo', 'npm'. "
                                "Default: 'auto'."
                            ),
                        },
                        "path": {
                            "type": "string",
                            "description": "Relative path to run tests from (default '.').",
                        },
                    },
                    "required": [],
                },
            ),
            lambda framework="auto", path=".": run_tests(policy, framework, path),
        ),
    }

    return EngineeringSpecialistPack(
        specialist_id="engineering",
        system_prompt=SYSTEM_PROMPT_ENGINEERING,
        tools=tools,
        finish_tool_def=_FINISH_TOOL_DEF,
        workspace_path=workspace_path,
        network_allowed=network_allowed,
    )
