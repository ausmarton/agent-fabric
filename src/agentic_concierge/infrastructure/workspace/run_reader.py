"""Read and summarise past runs from the workspace.

Provides lightweight, read-only access to run directories so the ``fabric logs``
CLI command and any future query tooling can list and inspect runs without
coupling to the write path (``FileSystemRunRepository``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class RunSummary:
    """Lightweight summary of a single run, built from its runlog."""
    run_id: str
    run_dir: str
    specialist_id: Optional[str]
    specialist_ids: List[str]
    routing_method: Optional[str]
    first_event_ts: Optional[float]
    event_count: int
    payload_summary: Optional[str]  # "summary" or "executive_summary" from finish payload


def _parse_runlog(runlog_path: Path) -> list[dict]:
    """Parse a runlog.jsonl file into a list of event dicts (silently skips bad lines)."""
    events: list[dict] = []
    try:
        for line in runlog_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    except OSError:
        pass
    return events


def _summarise_run(run_dir: Path) -> RunSummary:
    """Build a ``RunSummary`` from the run directory."""
    events = _parse_runlog(run_dir / "runlog.jsonl")

    specialist_id: Optional[str] = None
    specialist_ids: List[str] = []
    routing_method: Optional[str] = None
    first_ts: Optional[float] = None
    payload_summary: Optional[str] = None

    for ev in events:
        ts = ev.get("ts")
        if ts is not None and first_ts is None:
            first_ts = float(ts)

        if ev.get("kind") == "recruitment":
            p = ev.get("payload") or {}
            specialist_id = p.get("specialist_id")
            specialist_ids = p.get("specialist_ids") or (
                [specialist_id] if specialist_id else []
            )
            routing_method = p.get("routing_method")

        if ev.get("kind") == "tool_result":
            p = ev.get("payload") or {}
            tool = p.get("tool") or ""
            if tool == "finish_task":
                result = p.get("result") or {}
                payload_summary = (
                    result.get("summary")
                    or result.get("executive_summary")
                )

    return RunSummary(
        run_id=run_dir.name,
        run_dir=str(run_dir),
        specialist_id=specialist_id,
        specialist_ids=specialist_ids,
        routing_method=routing_method,
        first_event_ts=first_ts,
        event_count=len(events),
        payload_summary=payload_summary,
    )


def list_runs(workspace_root: str, limit: int = 20) -> List[RunSummary]:
    """List recent runs sorted by start time (most recent first).

    Scans ``{workspace_root}/runs/`` for subdirectories that contain a
    ``runlog.jsonl`` file.  Returns at most ``limit`` entries.
    """
    runs_dir = Path(workspace_root) / "runs"
    if not runs_dir.is_dir():
        return []

    summaries: List[RunSummary] = []
    for run_dir in runs_dir.iterdir():
        if not run_dir.is_dir():
            continue
        if not (run_dir / "runlog.jsonl").is_file():
            continue
        summaries.append(_summarise_run(run_dir))

    # Sort: most recent first (None timestamps sort last).
    summaries.sort(
        key=lambda s: s.first_event_ts if s.first_event_ts is not None else 0.0,
        reverse=True,
    )
    return summaries[:limit]


def read_run_events(run_id: str, workspace_root: str) -> List[dict]:
    """Return all runlog events for *run_id*.

    Looks up ``{workspace_root}/runs/{run_id}/runlog.jsonl``.

    Raises:
        FileNotFoundError: When the run directory or runlog does not exist.
    """
    run_dir = Path(workspace_root) / "runs" / run_id
    runlog = run_dir / "runlog.jsonl"
    if not runlog.is_file():
        raise FileNotFoundError(
            f"Run '{run_id}' not found in workspace '{workspace_root}'. "
            "Use 'fabric logs list' to see available runs."
        )
    return _parse_runlog(runlog)
