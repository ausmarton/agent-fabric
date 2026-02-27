"""Test runner tool: auto-detect and run the project's test suite."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Tuple

from .sandbox import SandboxPolicy, run_cmd

# Regex patterns for output parsing
_PYTEST_PASSED_RE = re.compile(r"(\d+) passed")
_PYTEST_FAILED_RE = re.compile(r"(\d+) failed")
_PYTEST_ERROR_RE = re.compile(r"(\d+) error(?:s)?")
_CARGO_RESULT_RE = re.compile(r"test result: (ok|FAILED)\. (\d+) passed; (\d+) failed")
_UNITTEST_RAN_RE = re.compile(r"Ran (\d+) tests?")
_UNITTEST_FAILED_RE = re.compile(r"FAILED \((?:failures=(\d+))?(?:,\s*)?(?:errors=(\d+))?\)")

_MAX_OUTPUT_CHARS = 3000


def _detect_framework(scan_root: Path) -> str:
    """Detect the test framework by scanning for project markers.

    Priority order:
    1. Cargo.toml → cargo test
    2. package.json with a "test" script → npm test
    3. pytest.ini, pyproject.toml[tool.pytest.ini_options], setup.cfg, or test_*.py/*_test.py → pytest
    4. Fallback → pytest (Python-first default)
    """
    # Cargo (Rust)
    if (scan_root / "Cargo.toml").exists():
        return "cargo"

    # npm (Node.js) — package.json with a "test" script
    pkg = scan_root / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text())
            if isinstance(data.get("scripts", {}).get("test"), str):
                return "npm"
        except Exception:
            pass

    # pytest.ini present
    if (scan_root / "pytest.ini").exists():
        return "pytest"

    # pyproject.toml with [tool.pytest.ini_options]
    pyproject = scan_root / "pyproject.toml"
    if pyproject.exists():
        try:
            if "[tool.pytest.ini_options]" in pyproject.read_text():
                return "pytest"
        except Exception:
            pass

    # setup.cfg with [tool:pytest]
    setup_cfg = scan_root / "setup.cfg"
    if setup_cfg.exists():
        try:
            if "[tool:pytest]" in setup_cfg.read_text():
                return "pytest"
        except Exception:
            pass

    # Any test_*.py or *_test.py files at root or one level deep
    test_files = (
        list(scan_root.glob("test_*.py"))
        + list(scan_root.glob("*_test.py"))
        + list(scan_root.glob("*/test_*.py"))
        + list(scan_root.glob("*/*_test.py"))
    )
    if test_files:
        return "pytest"

    return "pytest"  # Python-first default


def _parse_pytest_output(output: str) -> Tuple[bool, int, int, str]:
    """Parse pytest stdout/stderr. Returns (all_passed, failed_count, error_count, summary)."""
    passed_m = _PYTEST_PASSED_RE.search(output)
    failed_m = _PYTEST_FAILED_RE.search(output)
    error_m = _PYTEST_ERROR_RE.search(output)

    passed_count = int(passed_m.group(1)) if passed_m else 0
    failed_count = int(failed_m.group(1)) if failed_m else 0
    error_count = int(error_m.group(1)) if error_m else 0

    parts = []
    if passed_count:
        parts.append(f"{passed_count} passed")
    if failed_count:
        parts.append(f"{failed_count} failed")
    if error_count:
        parts.append(f"{error_count} error{'s' if error_count != 1 else ''}")

    summary = ", ".join(parts) if parts else "no test results detected"
    all_passed = failed_count == 0 and error_count == 0
    return all_passed, failed_count, error_count, summary


def _parse_cargo_output(output: str) -> Tuple[bool, int, int, str]:
    """Parse cargo test stdout. Returns (all_passed, failed_count, error_count, summary)."""
    m = _CARGO_RESULT_RE.search(output)
    if m:
        status, passed_count, failed_count = m.group(1), int(m.group(2)), int(m.group(3))
        all_passed = status == "ok" and failed_count == 0
        parts = [f"{passed_count} passed"]
        if failed_count:
            parts.append(f"{failed_count} failed")
        return all_passed, failed_count, 0, ", ".join(parts)
    return False, 0, 0, "no test results detected"


def _parse_unittest_output(output: str) -> Tuple[bool, int, int, str]:
    """Parse python -m unittest output. Returns (all_passed, failed_count, error_count, summary)."""
    ran_m = _UNITTEST_RAN_RE.search(output)
    fail_m = _UNITTEST_FAILED_RE.search(output)

    ran = int(ran_m.group(1)) if ran_m else 0
    failures = int(fail_m.group(1) or 0) if fail_m and fail_m.group(1) else 0
    errors = int(fail_m.group(2) or 0) if fail_m and fail_m.group(2) else 0

    all_passed = fail_m is None and ran > 0
    summary = f"{ran} ran"
    if failures:
        summary += f", {failures} failed"
    if errors:
        summary += f", {errors} errors"
    if not ran:
        summary = "no tests discovered"
    return all_passed, failures, errors, summary


def run_tests(
    policy: SandboxPolicy,
    framework: str = "auto",
    path: str = ".",
    timeout_s: int = 120,
) -> dict:
    """Auto-detect and run the project test suite.

    Uses ``run_cmd`` so the sandbox command allowlist applies.

    Args:
        policy: Sandbox policy (root + allowed_commands).
        framework: ``'auto'`` (detect), ``'pytest'``, ``'unittest'``, ``'cargo'``, or ``'npm'``.
        path: Relative path to the directory to run tests in (default ``'.'``).
        timeout_s: Per-test-run timeout in seconds.

    Returns:
        dict with keys: ``passed`` (bool), ``failed_count``, ``error_count``,
        ``summary`` (str), ``output`` (last 3000 chars), ``framework`` (str).
    """
    from .sandbox import safe_path

    # Resolve the test directory
    if path == ".":
        scan_root = policy.root.resolve()
    else:
        scan_root = safe_path(policy, path)

    # Detect framework
    detected = _detect_framework(scan_root) if framework == "auto" else framework
    if detected not in ("pytest", "unittest", "cargo", "npm"):
        detected = "pytest"

    # Build command — always use `python -m <runner>` so the sandbox Python
    # interpreter is used and no separate binary needs to be on PATH.
    if detected == "pytest":
        cmd = ["python", "-m", "pytest", "."]
    elif detected == "unittest":
        cmd = ["python", "-m", "unittest", "discover"]
    elif detected == "cargo":
        cmd = ["cargo", "test"]
    else:  # npm
        cmd = ["npm", "test"]

    # Run via sandbox
    try:
        result = run_cmd(policy, cmd, cwd=scan_root, timeout_s=timeout_s)
    except subprocess.TimeoutExpired:
        return {
            "passed": False,
            "failed_count": 0,
            "error_count": 1,
            "summary": f"Test suite timed out after {timeout_s}s",
            "output": "",
            "framework": detected,
        }

    combined = (result.get("stdout", "") + result.get("stderr", "")).strip()
    truncated = combined[-_MAX_OUTPUT_CHARS:] if len(combined) > _MAX_OUTPUT_CHARS else combined
    returncode = result.get("returncode", 1)

    # Parse output
    if detected == "pytest":
        all_passed, failed_count, error_count, summary = _parse_pytest_output(combined)
    elif detected == "unittest":
        all_passed, failed_count, error_count, summary = _parse_unittest_output(combined)
    elif detected == "cargo":
        all_passed, failed_count, error_count, summary = _parse_cargo_output(combined)
    else:
        # npm: trust exit code
        all_passed = returncode == 0
        failed_count = 0 if all_passed else 1
        error_count = 0
        summary = "passed" if all_passed else f"failed (exit code {returncode})"

    # If returncode indicates failure but parsing showed no failures, mark as failed
    if returncode != 0 and all_passed:
        all_passed = False
        if failed_count == 0 and error_count == 0:
            error_count = 1
            summary = (
                f"{summary} (exit code {returncode})"
                if summary != "no test results detected"
                else f"failed (exit code {returncode})"
            )

    return {
        "passed": all_passed,
        "failed_count": failed_count,
        "error_count": error_count,
        "summary": summary,
        "output": truncated,
        "framework": detected,
    }
