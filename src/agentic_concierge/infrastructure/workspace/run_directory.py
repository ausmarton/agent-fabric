"""Create run directories and resolve workspace paths."""

from __future__ import annotations

import random
import time
from pathlib import Path

from agentic_concierge.domain import RunId


def create_run_directory(workspace_root: str | Path) -> tuple[RunId, str, str]:
    """
    Create a new run directory under workspace_root/runs/<run_id>/ and workspace subdir.
    Returns (RunId, run_dir path, workspace path).
    """
    root = Path(workspace_root).resolve()
    ts = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    run_id_value = ts + "-" + "".join(random.choices("abcdef0123456789", k=6))
    run_dir = root / "runs" / run_id_value
    run_dir.mkdir(parents=True, exist_ok=True)
    workspace_path = run_dir / "workspace"
    workspace_path.mkdir(parents=True, exist_ok=True)
    return RunId(run_id_value), str(run_dir), str(workspace_path)
