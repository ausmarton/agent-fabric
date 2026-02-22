"""Engineering specialist pack: shell, read_file, write_file, list_files."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from agent_fabric.infrastructure.tools.sandbox import SandboxPolicy
from agent_fabric.infrastructure.tools.file_tools import read_text, write_text, list_tree
from agent_fabric.infrastructure.tools.shell_tools import run_shell

from .base import BaseSpecialistPack
from .prompts import TOOL_LOOP_ENGINEERING

SYSTEM_PROMPT = """You are an autonomous engineering team operating in a sandbox.
Quality > speed. Be precise. Prefer simple, correct solutions.

Hard rules:
- Do not claim something works unless you've verified via tools (tests/build/run).
- Use tools frequently. Capture outputs. If a tool fails, diagnose and fix.
- Write small, reviewable changes. Prefer adding tests.
- No destructive operations outside the sandbox.
- For any 'deploy/push' step: propose a plan and request human approval (do NOT execute).

Output discipline:
- When asked to produce code, modify files via write_file.
- When asked to run commands, use shell with explicit cmd arrays."""


def build_engineering_pack(workspace_path: str, _network_allowed: bool = False) -> BaseSpecialistPack:
    policy = SandboxPolicy(root=Path(workspace_path), network_allowed=True)
    tools: Dict[str, tuple[Dict[str, Any], Any]] = {
        "shell": (
            {"type": "object", "properties": {"cmd": {"type": "array", "items": {"type": "string"}}, "timeout_s": {"type": "integer"}}, "required": ["cmd"]},
            lambda cmd, timeout_s=120: run_shell(policy, cmd, timeout_s=timeout_s),
        ),
        "read_file": (
            {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            lambda path: read_text(policy, path),
        ),
        "write_file": (
            {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
            lambda path, content: write_text(policy, path, content),
        ),
        "list_files": (
            {"type": "object", "properties": {"max_files": {"type": "integer"}}, "required": []},
            lambda max_files=500: list_tree(policy, max_files=max_files),
        ),
    }
    return BaseSpecialistPack(
        specialist_id="engineering",
        system_prompt=SYSTEM_PROMPT,
        tool_loop_prompt_template=TOOL_LOOP_ENGINEERING,
        tools=tools,
    )
