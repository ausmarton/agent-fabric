"""Tests for infrastructure/workspace/run_checkpoint.py.

Covers:
- RunCheckpoint dataclass fields.
- save_checkpoint / load_checkpoint round-trip.
- Atomic write (tmp file renamed, no partial writes visible).
- delete_checkpoint removes the file.
- find_resumable_runs: returns run_ids with checkpoint but no run_complete.
- find_resumable_runs: excludes runs where runlog has run_complete event.
- load_checkpoint returns None for missing file.
- load_checkpoint returns None for corrupt JSON.
- save_checkpoint creates parent directory.
- Checkpoint with orchestration_plan round-trips correctly.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from agentic_concierge.infrastructure.workspace.run_checkpoint import (
    RunCheckpoint,
    delete_checkpoint,
    find_resumable_runs,
    load_checkpoint,
    save_checkpoint,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_checkpoint(run_dir: str, run_id: str = "run-1", **kwargs) -> RunCheckpoint:
    defaults = dict(
        run_id=run_id,
        run_dir=run_dir,
        workspace_path=str(Path(run_dir) / "workspace"),
        task_prompt="build a service",
        specialist_ids=["engineering"],
        completed_specialists=[],
        payloads={},
        task_force_mode="sequential",
        model_key="quality",
        routing_method="orchestrator",
        required_capabilities=["code_execution"],
        orchestration_plan=None,
        created_at=time.time(),
        updated_at=time.time(),
    )
    defaults.update(kwargs)
    return RunCheckpoint(**defaults)


# ---------------------------------------------------------------------------
# Basic round-trip
# ---------------------------------------------------------------------------

def test_save_load_round_trip(tmp_path):
    """save_checkpoint then load_checkpoint returns the same data."""
    run_dir = str(tmp_path / "run-1")
    cp = _make_checkpoint(run_dir, run_id="run-1")
    save_checkpoint(run_dir, cp)
    loaded = load_checkpoint(run_dir)

    assert loaded is not None
    assert loaded.run_id == "run-1"
    assert loaded.task_prompt == "build a service"
    assert loaded.specialist_ids == ["engineering"]
    assert loaded.model_key == "quality"


def test_save_creates_parent_directory(tmp_path):
    """save_checkpoint creates the run_dir if it doesn't exist."""
    run_dir = str(tmp_path / "nested" / "run-abc")
    cp = _make_checkpoint(run_dir, run_id="run-abc")
    save_checkpoint(run_dir, cp)  # should not raise
    assert (Path(run_dir) / "checkpoint.json").exists()


def test_load_missing_file_returns_none(tmp_path):
    """load_checkpoint returns None when checkpoint.json does not exist."""
    assert load_checkpoint(str(tmp_path / "nonexistent")) is None


def test_load_corrupt_json_returns_none(tmp_path):
    """load_checkpoint returns None on invalid JSON."""
    (tmp_path / "checkpoint.json").write_text("NOT JSON {{{")
    assert load_checkpoint(str(tmp_path)) is None


def test_save_is_atomic(tmp_path):
    """Atomic write: checkpoint.json.tmp should not exist after save."""
    run_dir = str(tmp_path)
    cp = _make_checkpoint(run_dir)
    save_checkpoint(run_dir, cp)
    assert not (tmp_path / "checkpoint.json.tmp").exists()
    assert (tmp_path / "checkpoint.json").exists()


# ---------------------------------------------------------------------------
# delete_checkpoint
# ---------------------------------------------------------------------------

def test_delete_removes_checkpoint(tmp_path):
    run_dir = str(tmp_path)
    cp = _make_checkpoint(run_dir)
    save_checkpoint(run_dir, cp)
    assert (tmp_path / "checkpoint.json").exists()
    delete_checkpoint(run_dir)
    assert not (tmp_path / "checkpoint.json").exists()


def test_delete_noop_when_no_checkpoint(tmp_path):
    """delete_checkpoint does not raise when checkpoint.json is absent."""
    delete_checkpoint(str(tmp_path))  # should not raise


# ---------------------------------------------------------------------------
# completed_specialists and payloads
# ---------------------------------------------------------------------------

def test_completed_specialists_round_trips(tmp_path):
    run_dir = str(tmp_path)
    cp = _make_checkpoint(
        run_dir,
        specialist_ids=["engineering", "research"],
        completed_specialists=["engineering"],
        payloads={"engineering": {"action": "final", "summary": "done"}},
    )
    save_checkpoint(run_dir, cp)
    loaded = load_checkpoint(run_dir)
    assert loaded.completed_specialists == ["engineering"]
    assert loaded.payloads["engineering"]["summary"] == "done"


def test_orchestration_plan_round_trips(tmp_path):
    """orchestration_plan dict is preserved through save/load."""
    run_dir = str(tmp_path)
    orch_plan = {
        "assignments": [{"specialist_id": "engineering", "brief": "build it"}],
        "mode": "sequential",
        "synthesis_required": False,
        "reasoning": "coding task",
    }
    cp = _make_checkpoint(run_dir, orchestration_plan=orch_plan)
    save_checkpoint(run_dir, cp)
    loaded = load_checkpoint(run_dir)
    assert loaded.orchestration_plan is not None
    assert loaded.orchestration_plan["assignments"][0]["brief"] == "build it"


# ---------------------------------------------------------------------------
# find_resumable_runs
# ---------------------------------------------------------------------------

def _write_runlog(run_dir: Path, events: list) -> None:
    runlog = run_dir / "runlog.jsonl"
    runlog.write_text("\n".join(json.dumps(e) for e in events))


def test_find_resumable_runs_returns_run_with_checkpoint(tmp_path):
    """A run with checkpoint.json and no run_complete event is resumable."""
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "run-abc"
    run_dir.mkdir(parents=True)
    cp = _make_checkpoint(str(run_dir), run_id="run-abc")
    save_checkpoint(str(run_dir), cp)
    _write_runlog(run_dir, [{"kind": "recruitment", "payload": {}}])

    resumable = find_resumable_runs(str(tmp_path))
    assert "run-abc" in resumable


def test_find_resumable_excludes_completed_run(tmp_path):
    """A run with run_complete in runlog is NOT resumable."""
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "run-done"
    run_dir.mkdir(parents=True)
    cp = _make_checkpoint(str(run_dir), run_id="run-done")
    save_checkpoint(str(run_dir), cp)
    _write_runlog(run_dir, [
        {"kind": "recruitment", "payload": {}},
        {"kind": "run_complete", "payload": {}},
    ])

    resumable = find_resumable_runs(str(tmp_path))
    assert "run-done" not in resumable


def test_find_resumable_returns_empty_when_no_runs(tmp_path):
    """Returns empty list when workspace has no runs dir."""
    assert find_resumable_runs(str(tmp_path)) == []


def test_find_resumable_returns_empty_when_no_checkpoints(tmp_path):
    """Returns empty list when runs exist but have no checkpoints."""
    run_dir = tmp_path / "runs" / "run-x"
    run_dir.mkdir(parents=True)
    _write_runlog(run_dir, [{"kind": "recruitment"}])
    assert find_resumable_runs(str(tmp_path)) == []


def test_find_resumable_run_with_no_runlog(tmp_path):
    """A run with checkpoint but no runlog at all is considered resumable."""
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "run-norunlog"
    run_dir.mkdir(parents=True)
    cp = _make_checkpoint(str(run_dir), run_id="run-norunlog")
    save_checkpoint(str(run_dir), cp)
    # No runlog created

    resumable = find_resumable_runs(str(tmp_path))
    assert "run-norunlog" in resumable
