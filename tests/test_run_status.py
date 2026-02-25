"""Tests for P8-3: GET /runs/{run_id}/status endpoint.

Tests cover:
- Returns 404 when run_id not found
- Returns {"status": "running"} when run dir exists but no run_complete event
- Returns {"status": "completed", "specialist_ids": [...]} when run_complete found
- Returns {"status": "running"} when events exist but no run_complete yet
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from agent_fabric.interfaces.http_api import app


def _write_runlog(run_dir: str, events: list) -> None:
    """Write events to a runlog.jsonl in the given run dir."""
    runlog_path = Path(run_dir) / "runlog.jsonl"
    with open(runlog_path, "w") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")


def test_run_status_404_when_not_found():
    """Returns 404 for an unknown run_id."""
    with tempfile.TemporaryDirectory() as workspace_root:
        with patch("agent_fabric.interfaces.http_api._workspace_root", return_value=workspace_root):
            client = TestClient(app)
            response = client.get("/runs/nonexistent-run-id/status")
        assert response.status_code == 404


def test_run_status_completed_when_run_complete_event_present():
    """Returns completed status when run_complete event exists in runlog."""
    with tempfile.TemporaryDirectory() as workspace_root:
        run_id = "test-run-complete"
        run_dir = Path(workspace_root) / "runs" / run_id
        run_dir.mkdir(parents=True)

        events = [
            {"kind": "recruitment", "data": {"specialist_id": "engineering", "specialist_ids": ["engineering"]}, "step": None},
            {"kind": "run_complete", "data": {"run_id": run_id, "specialist_ids": ["engineering"], "task_force_mode": "sequential"}, "step": None},
        ]
        _write_runlog(str(run_dir), events)

        with patch("agent_fabric.interfaces.http_api._workspace_root", return_value=workspace_root):
            client = TestClient(app)
            response = client.get(f"/runs/{run_id}/status")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "completed"
        assert body["run_id"] == run_id
        assert "engineering" in body["specialist_ids"]


def test_run_status_running_when_no_run_complete():
    """Returns running status when events exist but no run_complete."""
    with tempfile.TemporaryDirectory() as workspace_root:
        run_id = "test-run-in-progress"
        run_dir = Path(workspace_root) / "runs" / run_id
        run_dir.mkdir(parents=True)

        events = [
            {"kind": "recruitment", "data": {"specialist_id": "engineering", "specialist_ids": ["engineering"]}, "step": None},
            {"kind": "llm_request", "data": {"step": 0, "message_count": 2}, "step": "step_0"},
        ]
        _write_runlog(str(run_dir), events)

        with patch("agent_fabric.interfaces.http_api._workspace_root", return_value=workspace_root):
            client = TestClient(app)
            response = client.get(f"/runs/{run_id}/status")

        assert response.status_code == 200
        assert response.json()["status"] == "running"


def test_run_status_running_when_empty_runlog():
    """Returns running status when run dir exists but runlog is empty."""
    with tempfile.TemporaryDirectory() as workspace_root:
        run_id = "test-run-empty"
        run_dir = Path(workspace_root) / "runs" / run_id
        run_dir.mkdir(parents=True)
        # Create empty runlog
        (run_dir / "runlog.jsonl").write_text("")

        with patch("agent_fabric.interfaces.http_api._workspace_root", return_value=workspace_root):
            client = TestClient(app)
            response = client.get(f"/runs/{run_id}/status")

        assert response.status_code == 200
        assert response.json()["status"] == "running"


def test_run_status_includes_task_force_mode():
    """Completed response includes task_force_mode from the run_complete event."""
    with tempfile.TemporaryDirectory() as workspace_root:
        run_id = "test-parallel-complete"
        run_dir = Path(workspace_root) / "runs" / run_id
        run_dir.mkdir(parents=True)

        events = [
            {"kind": "run_complete", "data": {
                "run_id": run_id,
                "specialist_ids": ["engineering", "research"],
                "task_force_mode": "parallel",
            }, "step": None},
        ]
        _write_runlog(str(run_dir), events)

        with patch("agent_fabric.interfaces.http_api._workspace_root", return_value=workspace_root):
            client = TestClient(app)
            response = client.get(f"/runs/{run_id}/status")

        body = response.json()
        assert body["status"] == "completed"
        assert body["task_force_mode"] == "parallel"
        assert body["specialist_ids"] == ["engineering", "research"]


def test_run_status_run_dir_without_runlog_returns_running():
    """Run dir exists but no runlog.jsonl → returns running (directory may be initializing)."""
    with tempfile.TemporaryDirectory() as workspace_root:
        run_id = "test-no-runlog"
        run_dir = Path(workspace_root) / "runs" / run_id
        run_dir.mkdir(parents=True)
        # No runlog.jsonl at all

        with patch("agent_fabric.interfaces.http_api._workspace_root", return_value=workspace_root):
            client = TestClient(app)
            response = client.get(f"/runs/{run_id}/status")

        assert response.status_code == 200
        assert response.json()["status"] == "running"
