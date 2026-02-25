"""Tests for 'fabric run --stream' CLI flag and _render_stream_event helper."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from agent_fabric.interfaces.cli import _render_stream_event, _result_summary, app


runner = CliRunner()


# ---------------------------------------------------------------------------
# _result_summary helper
# ---------------------------------------------------------------------------

def test_result_summary_content():
    result = _result_summary({"content": "hello world"})
    assert "chars" in result
    assert "11" in result


def test_result_summary_content_length():
    assert "chars" in _result_summary({"content": "x" * 200})


def test_result_summary_files():
    assert _result_summary({"count": 5, "files": []}) == "5 files"


def test_result_summary_shell_rc():
    s = _result_summary({"returncode": 0, "stdout": "ok", "stderr": ""})
    assert "rc=0" in s


def test_result_summary_bytes():
    assert _result_summary({"bytes": 100, "path": "foo.py"}) == "100 bytes → foo.py"


def test_result_summary_path():
    assert _result_summary({"path": "src/app.py"}) == "src/app.py"


def test_result_summary_unknown():
    assert isinstance(_result_summary({"weird": "thing"}), str)


def test_result_summary_non_dict():
    assert "hello" in _result_summary("hello")


# ---------------------------------------------------------------------------
# _render_stream_event — smoke tests (no assertion on exact text, just no crash)
# ---------------------------------------------------------------------------

class _MockConsole:
    """Captures print calls."""
    def __init__(self):
        self.lines = []

    def print(self, text="", **_):
        self.lines.append(str(text))


def _render(kind, data=None, step=None):
    console = _MockConsole()
    _render_stream_event(console, {"kind": kind, "data": data or {}, "step": step})
    return console.lines


def test_render_recruitment():
    lines = _render("recruitment", {"specialist_ids": ["engineering"], "required_capabilities": ["code_execution"]})
    assert any("engineering" in l for l in lines)


def test_render_llm_request():
    lines = _render("llm_request", {"step": 1, "message_count": 3}, step="step_1")
    assert lines  # at least one line


def test_render_tool_call():
    lines = _render("tool_call", {"tool": "write_file", "args": {"path": "app.py"}}, step="step_0")
    assert any("write_file" in l for l in lines)


def test_render_tool_result_success():
    lines = _render("tool_result", {"tool": "write_file", "result": {"bytes": 42, "path": "app.py"}})
    assert any("write_file" in l for l in lines)
    assert any("42" in l for l in lines)


def test_render_tool_result_error():
    lines = _render("tool_result", {"tool": "write_file", "result": {"error": "permission_denied", "message": "use relative path"}})
    assert any("write_file" in l for l in lines)


def test_render_tool_error():
    lines = _render("tool_error", {"tool": "shell", "error_type": "permission", "error_message": "disallowed"})
    assert any("shell" in l for l in lines)


def test_render_security_event():
    lines = _render("security_event", {"error_message": "path escape"})
    assert any("sandbox" in l.lower() for l in lines)


def test_render_corrective_reprompt():
    lines = _render("corrective_reprompt", {"attempt": 1, "max_retries": 2})
    assert any("re-prompt" in l or "reprompt" in l.lower() for l in lines)


def test_render_cloud_fallback():
    lines = _render("cloud_fallback", {"reason": "no_tool_calls", "cloud_model": "gpt-4o"})
    assert any("cloud" in l.lower() or "gpt-4o" in l for l in lines)


def test_render_pack_start():
    lines = _render("pack_start", {"specialist_id": "research"})
    assert any("research" in l for l in lines)


def test_render_run_complete_no_output():
    # run_complete is handled silently (final panel is printed outside)
    lines = _render("run_complete", {"run_id": "abc", "specialist_ids": ["engineering"]})
    assert lines == []


def test_render_run_error():
    lines = _render("_run_error_", {"error": "LLM unreachable"})
    assert any("failed" in l.lower() or "error" in l.lower() for l in lines)


# ---------------------------------------------------------------------------
# fabric run --stream integration (mocked execute_task)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_with_streaming_renders_events(tmp_path):
    """_run_with_streaming consumes events and returns the RunResult."""
    from agent_fabric.domain import RunId, RunResult
    from agent_fabric.interfaces.cli import _run_with_streaming

    events_to_emit = [
        {"kind": "recruitment", "data": {"specialist_ids": ["engineering"], "required_capabilities": []}, "step": None},
        {"kind": "tool_call", "data": {"tool": "list_files", "args": {}}, "step": "step_0"},
        {"kind": "tool_result", "data": {"tool": "list_files", "result": {"count": 0, "files": []}}, "step": "step_0"},
        {"kind": "run_complete", "data": {"run_id": "x", "specialist_ids": ["engineering"]}, "step": None},
    ]

    mock_result = RunResult(
        run_id=RunId("x"), run_dir=str(tmp_path), workspace_path=str(tmp_path / "w"),
        specialist_id="engineering", model_name="mock",
        payload={"action": "final", "summary": "done"},
    )

    async def _fake_execute(task, **kwargs):
        q = kwargs.get("event_queue")
        for ev in events_to_emit:
            if q is not None:
                await q.put(ev)
        return mock_result

    mock_chat = MagicMock()
    mock_repo = MagicMock()
    mock_registry = MagicMock()
    mock_config = MagicMock()
    mock_model_cfg = MagicMock()
    task = MagicMock()

    with patch("agent_fabric.interfaces.cli.execute_task", side_effect=_fake_execute):
        result = await _run_with_streaming(
            task, mock_chat, mock_repo, mock_registry, mock_config, mock_model_cfg
        )

    assert result.run_id.value == "x"
    assert result.payload["summary"] == "done"
