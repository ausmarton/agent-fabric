"""Tests for 'fabric logs' subcommands and run_reader infrastructure (Phase 4)."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentic_concierge.interfaces.cli import app
from agentic_concierge.infrastructure.workspace.run_reader import (
    RunSummary,
    list_runs,
    read_run_events,
)


runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers — create fake run directories
# ---------------------------------------------------------------------------

def _make_run(
    workspace: Path,
    run_id: str,
    specialist_ids: list[str],
    ts: float,
    event_count: int = 3,
    payload_summary: str | None = "Task done",
) -> Path:
    """Create a minimal fake run directory with a runlog.jsonl."""
    run_dir = workspace / "runs" / run_id
    (run_dir / "workspace").mkdir(parents=True, exist_ok=True)

    events = [
        {
            "ts": ts,
            "kind": "recruitment",
            "step": None,
            "payload": {
                "specialist_id": specialist_ids[0],
                "specialist_ids": specialist_ids,
                "required_capabilities": [],
                "routing_method": "explicit",
                "is_task_force": len(specialist_ids) > 1,
            },
        },
        {
            "ts": ts + 0.1,
            "kind": "llm_request",
            "step": "step_0",
            "payload": {"step": 0, "message_count": 2},
        },
        {
            "ts": ts + 0.5,
            "kind": "tool_result",
            "step": "step_0",
            "payload": {
                "tool": "finish_task",
                "result": {
                    "status": "task_completed",
                    "summary": payload_summary,
                },
            },
        },
    ]
    # Allow specifying a different event count.
    events = events[:event_count]

    runlog = run_dir / "runlog.jsonl"
    runlog.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
    return run_dir


# ---------------------------------------------------------------------------
# list_runs
# ---------------------------------------------------------------------------

def test_list_runs_empty_workspace(tmp_path):
    summaries = list_runs(str(tmp_path))
    assert summaries == []


def test_list_runs_no_runs_dir(tmp_path):
    """When workspace exists but has no 'runs/' subdir, list_runs returns []."""
    (tmp_path / "something_else").mkdir()
    assert list_runs(str(tmp_path)) == []


def test_list_runs_returns_summaries(tmp_path):
    _make_run(tmp_path, "run_001", ["engineering"], ts=1000.0)
    _make_run(tmp_path, "run_002", ["research"], ts=2000.0)

    summaries = list_runs(str(tmp_path))
    assert len(summaries) == 2
    ids = {s.run_id for s in summaries}
    assert ids == {"run_001", "run_002"}


def test_list_runs_sorted_most_recent_first(tmp_path):
    _make_run(tmp_path, "run_old", ["engineering"], ts=1000.0)
    _make_run(tmp_path, "run_new", ["research"], ts=9000.0)
    _make_run(tmp_path, "run_mid", ["research"], ts=5000.0)

    summaries = list_runs(str(tmp_path))
    assert summaries[0].run_id == "run_new"
    assert summaries[1].run_id == "run_mid"
    assert summaries[2].run_id == "run_old"


def test_list_runs_respects_limit(tmp_path):
    for i in range(5):
        _make_run(tmp_path, f"run_{i:03}", ["engineering"], ts=float(i * 100))

    summaries = list_runs(str(tmp_path), limit=3)
    assert len(summaries) == 3


def test_list_runs_skips_dirs_without_runlog(tmp_path):
    (tmp_path / "runs" / "stale_run").mkdir(parents=True)  # no runlog.jsonl
    _make_run(tmp_path, "good_run", ["engineering"], ts=1000.0)

    summaries = list_runs(str(tmp_path))
    assert len(summaries) == 1
    assert summaries[0].run_id == "good_run"


def test_list_runs_extracts_specialist_ids(tmp_path):
    _make_run(tmp_path, "run_tf", ["engineering", "research"], ts=1000.0)

    s = list_runs(str(tmp_path))[0]
    assert s.specialist_ids == ["engineering", "research"]
    assert s.specialist_id == "engineering"


def test_list_runs_extracts_payload_summary(tmp_path):
    _make_run(tmp_path, "run_a", ["engineering"], ts=1000.0, payload_summary="Created API server")

    s = list_runs(str(tmp_path))[0]
    assert s.payload_summary == "Created API server"


# ---------------------------------------------------------------------------
# read_run_events
# ---------------------------------------------------------------------------

def test_read_run_events_returns_events(tmp_path):
    _make_run(tmp_path, "run_x", ["engineering"], ts=1000.0)

    events = read_run_events("run_x", str(tmp_path))
    assert len(events) == 3
    kinds = [e["kind"] for e in events]
    assert "recruitment" in kinds
    assert "llm_request" in kinds
    assert "tool_result" in kinds


def test_read_run_events_raises_for_unknown_run(tmp_path):
    with pytest.raises(FileNotFoundError, match="Run 'no_such_run' not found"):
        read_run_events("no_such_run", str(tmp_path))


def test_read_run_events_tolerates_bad_lines(tmp_path):
    """Lines that can't be parsed as JSON are silently skipped."""
    run_dir = tmp_path / "runs" / "run_bad"
    run_dir.mkdir(parents=True)
    (run_dir / "runlog.jsonl").write_text(
        '{"kind": "llm_request", "ts": 1}\n'
        "not valid json\n"
        '{"kind": "tool_result", "ts": 2}\n',
        encoding="utf-8",
    )
    events = read_run_events("run_bad", str(tmp_path))
    assert len(events) == 2


# ---------------------------------------------------------------------------
# CLI: fabric logs list
# ---------------------------------------------------------------------------

def test_cli_logs_list_empty_workspace(tmp_path):
    result = runner.invoke(app, ["logs", "list", "--workspace", str(tmp_path)])
    assert result.exit_code == 0
    assert "No runs found" in result.output


def test_cli_logs_list_shows_run_ids(tmp_path):
    _make_run(tmp_path, "run_abc123", ["engineering"], ts=1000.0)
    result = runner.invoke(app, ["logs", "list", "--workspace", str(tmp_path)])
    assert result.exit_code == 0
    assert "run_abc123" in result.output


def test_cli_logs_list_shows_specialists(tmp_path):
    _make_run(tmp_path, "run_tf", ["engineering", "research"], ts=1000.0)
    result = runner.invoke(app, ["logs", "list", "--workspace", str(tmp_path)])
    assert result.exit_code == 0
    assert "engineering" in result.output
    assert "research" in result.output


def test_cli_logs_list_respects_limit_option(tmp_path):
    for i in range(5):
        _make_run(tmp_path, f"run_{i:03}", ["engineering"], ts=float(i * 100 + 1))
    result = runner.invoke(app, ["logs", "list", "--workspace", str(tmp_path), "--limit", "2"])
    assert result.exit_code == 0
    # Only 2 run IDs should appear
    shown = [line for line in result.output.splitlines() if "run_" in line]
    assert len(shown) == 2


# ---------------------------------------------------------------------------
# CLI: fabric logs show
# ---------------------------------------------------------------------------

def test_cli_logs_show_displays_events(tmp_path):
    _make_run(tmp_path, "run_show", ["engineering"], ts=1000.0)
    result = runner.invoke(app, ["logs", "show", "run_show", "--workspace", str(tmp_path)])
    assert result.exit_code == 0
    assert "recruitment" in result.output
    assert "llm_request" in result.output


def test_cli_logs_show_unknown_run_exits_1(tmp_path):
    result = runner.invoke(app, ["logs", "show", "does_not_exist", "--workspace", str(tmp_path)])
    assert result.exit_code == 1


def test_cli_logs_show_kinds_filter(tmp_path):
    _make_run(tmp_path, "run_filter", ["engineering"], ts=1000.0)
    result = runner.invoke(
        app,
        ["logs", "show", "run_filter", "--workspace", str(tmp_path), "--kinds", "llm_request"],
    )
    assert result.exit_code == 0
    assert "llm_request" in result.output
    # Recruitment event must be filtered out
    assert "recruitment" not in result.output
