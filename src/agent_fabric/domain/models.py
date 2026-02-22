"""Domain models: RunId, Task, RunResult. Pure data, no I/O."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class RunId:
    """Unique identifier for a single run (e.g. timestamp + random suffix)."""
    value: str


@dataclass
class Task:
    """User task: prompt and optional constraints."""
    prompt: str
    specialist_id: str | None = None  # If set, use this specialist; else recruit
    model_key: str = "quality"
    network_allowed: bool = True


@dataclass
class RunResult:
    """Result of executing a task: run id, paths, and final payload."""
    run_id: RunId
    run_dir: str
    workspace_path: str
    specialist_id: str
    model_name: str
    payload: Dict[str, Any]
    # Optional: required_capabilities, selected_specialists (for future multi-pack)
