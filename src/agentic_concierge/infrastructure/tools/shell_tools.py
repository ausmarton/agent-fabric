"""Shell tool: run allowlisted commands in sandbox."""

from __future__ import annotations

from typing import List

from .sandbox import SandboxPolicy, run_cmd


def run_shell(policy: SandboxPolicy, cmd: List[str], timeout_s: int = 120) -> dict:
    return run_cmd(policy, cmd, timeout_s=timeout_s)
