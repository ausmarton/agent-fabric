"""Run checkpoint: save/load/delete interrupted run state for session continuation.

Checkpoint files are written atomically (write-to-tmp + rename) to prevent
corrupt checkpoints on crash.  The file format is plain JSON for easy
inspection.  Each checkpoint lives at ``{run_dir}/checkpoint.json``.

Phase 12-11 to 12-12.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class RunCheckpoint:
    """State snapshot of an in-progress run, used for session continuation.

    Fields:
        run_id: The run identifier (directory name under ``runs/``).
        run_dir: Absolute path to the run directory.
        workspace_path: Absolute path to the specialist workspace.
        task_prompt: Original task prompt.
        specialist_ids: Ordered list of all specialist IDs for this run.
        completed_specialists: IDs of specialists that have already finished.
        payloads: Mapping of specialist_id → finish_task payload for completed specialists.
        task_force_mode: ``"sequential"`` or ``"parallel"``.
        model_key: Model key used for task execution (e.g. ``"quality"``).
        routing_method: How specialists were recruited (``"orchestrator"``, etc.).
        required_capabilities: Capability IDs inferred for this task.
        orchestration_plan: Serialized ``OrchestrationPlan`` dict, or ``None``.
        created_at: Unix timestamp of initial checkpoint creation.
        updated_at: Unix timestamp of last checkpoint update.
    """

    run_id: str
    run_dir: str
    workspace_path: str
    task_prompt: str
    specialist_ids: List[str]
    completed_specialists: List[str]
    payloads: Dict[str, Any]
    task_force_mode: str
    model_key: str
    routing_method: str
    required_capabilities: List[str]
    orchestration_plan: Optional[Dict[str, Any]]
    created_at: float
    updated_at: float


def save_checkpoint(run_dir: str, checkpoint: RunCheckpoint) -> None:
    """Atomically write the checkpoint to ``{run_dir}/checkpoint.json``.

    Uses a write-to-tmp-then-rename strategy to prevent partially-written
    checkpoint files from being loaded after a crash.
    """
    run_dir_path = Path(run_dir)
    run_dir_path.mkdir(parents=True, exist_ok=True)

    tmp_file = run_dir_path / "checkpoint.json.tmp"
    final_file = run_dir_path / "checkpoint.json"

    data = {
        "run_id": checkpoint.run_id,
        "run_dir": checkpoint.run_dir,
        "workspace_path": checkpoint.workspace_path,
        "task_prompt": checkpoint.task_prompt,
        "specialist_ids": checkpoint.specialist_ids,
        "completed_specialists": checkpoint.completed_specialists,
        "payloads": checkpoint.payloads,
        "task_force_mode": checkpoint.task_force_mode,
        "model_key": checkpoint.model_key,
        "routing_method": checkpoint.routing_method,
        "required_capabilities": checkpoint.required_capabilities,
        "orchestration_plan": checkpoint.orchestration_plan,
        "created_at": checkpoint.created_at,
        "updated_at": checkpoint.updated_at,
    }
    tmp_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp_file.rename(final_file)


def load_checkpoint(run_dir: str) -> Optional[RunCheckpoint]:
    """Load a checkpoint from ``{run_dir}/checkpoint.json``.

    Returns ``None`` if the file does not exist or cannot be parsed.
    """
    checkpoint_file = Path(run_dir) / "checkpoint.json"
    if not checkpoint_file.exists():
        return None

    try:
        data = json.loads(checkpoint_file.read_text())
        return RunCheckpoint(
            run_id=data["run_id"],
            run_dir=data["run_dir"],
            workspace_path=data["workspace_path"],
            task_prompt=data["task_prompt"],
            specialist_ids=data["specialist_ids"],
            completed_specialists=data.get("completed_specialists", []),
            payloads=data.get("payloads", {}),
            task_force_mode=data.get("task_force_mode", "sequential"),
            model_key=data.get("model_key", "quality"),
            routing_method=data.get("routing_method", "unknown"),
            required_capabilities=data.get("required_capabilities", []),
            orchestration_plan=data.get("orchestration_plan"),
            created_at=data.get("created_at", 0.0),
            updated_at=data.get("updated_at", 0.0),
        )
    except Exception as exc:
        logger.warning("Failed to load checkpoint from %s: %s", run_dir, exc)
        return None


def delete_checkpoint(run_dir: str) -> None:
    """Remove ``{run_dir}/checkpoint.json`` if it exists."""
    cp = Path(run_dir) / "checkpoint.json"
    if cp.exists():
        cp.unlink()


def find_resumable_runs(workspace_root: str) -> List[str]:
    """Return run_ids that have a checkpoint but no ``run_complete`` event in their runlog.

    A run is considered resumable when:
    - ``{workspace_root}/runs/{run_id}/checkpoint.json`` exists, AND
    - The run's ``runlog.jsonl`` does not contain a ``run_complete`` event
      (or the runlog does not exist yet).
    """
    runs_dir = Path(workspace_root) / "runs"
    if not runs_dir.exists():
        return []

    resumable: List[str] = []
    for checkpoint_file in sorted(runs_dir.glob("*/checkpoint.json")):
        run_id = checkpoint_file.parent.name
        runlog = checkpoint_file.parent / "runlog.jsonl"

        if not runlog.exists():
            resumable.append(run_id)
            continue

        # Check if runlog has a run_complete event
        has_complete = False
        try:
            for line in runlog.read_text().splitlines():
                if line.strip():
                    event = json.loads(line)
                    if event.get("kind") == "run_complete":
                        has_complete = True
                        break
        except Exception:
            pass

        if not has_complete:
            resumable.append(run_id)

    return resumable
