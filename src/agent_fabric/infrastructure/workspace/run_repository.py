"""File-system run repository: composes run directory and run log. Implements RunRepository port."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from agent_fabric.domain import RunId

from .run_directory import create_run_directory
from .run_log import append_event as append_run_log_event


class FileSystemRunRepository:
    """Creates runs via run_directory; appends events via run_log."""

    def __init__(self, workspace_root: str = ".fabric"):
        self._workspace_root = Path(workspace_root)

    def create_run(self) -> tuple[RunId, str, str]:
        return create_run_directory(self._workspace_root)

    def append_event(
        self,
        run_id: RunId,
        kind: str,
        payload: Dict[str, Any],
        step: str | None = None,
    ) -> None:
        run_dir = self._workspace_root.resolve() / "runs" / run_id.value
        append_run_log_event(run_dir, kind, payload, step)
