"""Tests for sandbox path safety."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from agent_fabric.infrastructure.tools.sandbox import SandboxPolicy, safe_path


def test_safe_path_within_root():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "a").mkdir()
        policy = SandboxPolicy(root=root)
        p = safe_path(policy, "a/file.txt")
        assert p == root / "a" / "file.txt"


@pytest.mark.parametrize("escape_path", [
    "../etc/passwd",
    "..",
    "a/../../etc/passwd",
])
def test_safe_path_escape_fails(tmp_path, escape_path):
    policy = SandboxPolicy(root=tmp_path)
    with pytest.raises(PermissionError):
        safe_path(policy, escape_path)
