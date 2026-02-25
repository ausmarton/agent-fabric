"""Sandbox policy and path safety."""

from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from agent_fabric.config.constants import MAX_TOOL_OUTPUT_CHARS, SHELL_DEFAULT_TIMEOUT_S


@dataclass
class SandboxPolicy:
    root: Path
    allowed_commands: Tuple[str, ...] = (
        "python", "python3", "pytest", "bash", "sh", "git", "rg", "ls", "cat", "sed", "awk", "jq", "pip", "uv", "make"
    )
    network_allowed: bool = True
    max_output_chars: int = MAX_TOOL_OUTPUT_CHARS


def _truncate(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    return s[:limit] + f"\n... [truncated {len(s)-limit} chars]"


def run_cmd(
    policy: SandboxPolicy,
    cmd: List[str],
    cwd: Optional[Path] = None,
    timeout_s: int = SHELL_DEFAULT_TIMEOUT_S,
) -> dict:
    if not cmd:
        raise ValueError("Empty command")
    exe = cmd[0]
    if exe not in policy.allowed_commands:
        raise PermissionError(f"Command not allowed: {exe}. Allowed: {policy.allowed_commands}")
    workdir = cwd or policy.root
    workdir = workdir.resolve()
    if policy.root.resolve() not in workdir.parents and workdir != policy.root.resolve():
        raise PermissionError("cwd must be within sandbox root")
    env = os.environ.copy()
    env["FABRIC_SANDBOX_ROOT"] = str(policy.root)
    p = subprocess.run(
        cmd, cwd=str(workdir), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout_s,
    )
    return {
        "cmd": " ".join(shlex.quote(x) for x in cmd),
        "returncode": p.returncode,
        "stdout": _truncate(p.stdout, policy.max_output_chars),
        "stderr": _truncate(p.stderr, policy.max_output_chars),
    }


def safe_path(policy: SandboxPolicy, rel_path: str) -> Path:
    if rel_path.startswith("/"):
        raise PermissionError(
            f"Path must be relative (e.g. 'app.py' or 'src/app.py'), "
            f"not an absolute path. Got: {rel_path!r}"
        )
    p = (policy.root / rel_path).resolve()
    if policy.root.resolve() not in p.parents and p != policy.root.resolve():
        raise PermissionError(
            f"Path {rel_path!r} resolves outside the workspace sandbox. "
            "Use a relative path that stays within the workspace."
        )
    return p
