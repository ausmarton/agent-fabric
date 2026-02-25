"""Unit tests for execute_task: tool loop correctness, finish_task validation,
tool error classification, plain-text response handling, and max_steps behaviour.

These tests patch the LLM client so no real server is needed.  The
FileSystemRunRepository and ConfigSpecialistRegistry are real so the run
directory structure is also exercised.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agent_fabric.application.execute_task import execute_task
from agent_fabric.config import load_config
from agent_fabric.domain import LLMResponse, RunResult, Task, ToolCallRequest
from agent_fabric.infrastructure.ollama import OllamaChatClient
from agent_fabric.infrastructure.specialists import ConfigSpecialistRegistry
from agent_fabric.infrastructure.specialists.base import BaseSpecialistPack
from agent_fabric.infrastructure.workspace import FileSystemRunRepository


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _finish_response(call_id: str = "c1", **kwargs) -> LLMResponse:
    """LLMResponse that calls finish_task with the given arguments."""
    defaults = {"summary": "Done", "artifacts": [], "next_steps": [], "notes": ""}
    defaults.update(kwargs)
    return LLMResponse(
        content=None,
        tool_calls=[ToolCallRequest(call_id=call_id, tool_name="finish_task", arguments=defaults)],
    )


def _tool_response(tool_name: str, call_id: str = "c1", **kwargs) -> LLMResponse:
    """LLMResponse that calls a non-finish tool."""
    return LLMResponse(
        content=None,
        tool_calls=[ToolCallRequest(call_id=call_id, tool_name=tool_name, arguments=kwargs)],
    )


def _read_runlog(run_dir: str) -> list[dict]:
    lines = Path(run_dir, "runlog.jsonl").read_text().strip().splitlines()
    return [json.loads(ln) for ln in lines if ln]


async def _run(chat_mock_responses, *, tmp_path, specialist_id="engineering", max_steps=10):
    """Execute a task with the given sequential mock LLM responses."""
    config = load_config()
    run_repository = FileSystemRunRepository(workspace_root=str(tmp_path))
    specialist_registry = ConfigSpecialistRegistry(config)
    with patch.object(OllamaChatClient, "chat", new_callable=AsyncMock,
                      side_effect=chat_mock_responses):
        chat_client = OllamaChatClient(base_url="http://localhost:11434/v1", timeout_s=5.0)
        task = Task(prompt="test task", specialist_id=specialist_id, network_allowed=False)
        return await execute_task(
            task,
            chat_client=chat_client,
            run_repository=run_repository,
            specialist_registry=specialist_registry,
            config=config,
            max_steps=max_steps,
        )


# ---------------------------------------------------------------------------
# finish_task validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_finish_task_empty_args_rejected_and_llm_retried(tmp_path):
    """finish_task({}) must be rejected; error returned to LLM; a subsequent valid call succeeds."""
    prior_tool = _tool_response("list_files", call_id="c0")
    invalid_call = LLMResponse(
        content=None,
        tool_calls=[ToolCallRequest(call_id="c1", tool_name="finish_task", arguments={})],
    )
    valid_call = _finish_response(call_id="c2")

    result = await _run([prior_tool, invalid_call, valid_call], tmp_path=tmp_path)

    # Loop must have continued past the invalid call.
    events = _read_runlog(result.run_dir)
    llm_requests = [e for e in events if e["kind"] == "llm_request"]
    assert len(llm_requests) == 3, "LLM should be called three times (tool, invalid finish, valid finish)"

    # Final payload must come from the valid third call.
    assert result.payload["action"] == "final"
    assert result.payload["summary"] == "Done"

    # The finish_task tool_result with the validation error must be present.
    finish_errors = [
        e for e in events
        if e["kind"] == "tool_result"
        and e["payload"]["tool"] == "finish_task"
        and "missing_fields" in e["payload"].get("result", {})
    ]
    assert len(finish_errors) == 1
    assert "summary" in finish_errors[0]["payload"]["result"]["missing_fields"]


@pytest.mark.asyncio
async def test_finish_task_missing_required_field_rejected(tmp_path):
    """finish_task without 'summary' must be rejected; only the complete call is accepted."""
    prior_tool = _tool_response("list_files", call_id="c0")
    # Engineering pack requires 'summary'. Provide artifacts but not summary.
    incomplete = LLMResponse(
        content=None,
        tool_calls=[ToolCallRequest(
            call_id="c1",
            tool_name="finish_task",
            arguments={"artifacts": ["output.txt"], "notes": ""},
        )],
    )
    valid_call = _finish_response(call_id="c2")

    result = await _run([prior_tool, incomplete, valid_call], tmp_path=tmp_path)

    assert result.payload["action"] == "final"
    assert result.payload["summary"] == "Done"

    events = _read_runlog(result.run_dir)
    # Find the finish_task tool_result that carries the missing-fields error.
    error_result = next(
        e for e in events
        if e["kind"] == "tool_result"
        and e["payload"]["tool"] == "finish_task"
        and "missing_fields" in e["payload"].get("result", {})
    )
    assert "summary" in error_result["payload"]["result"]["missing_fields"]


@pytest.mark.asyncio
async def test_finish_task_valid_args_accepted_after_prior_tool_call(tmp_path):
    """finish_task with all required fields is accepted after a tool has been used (no required-field retry)."""
    result = await _run(
        [_tool_response("list_files", call_id="c1"), _finish_response(call_id="c2")],
        tmp_path=tmp_path,
    )

    assert result.payload["action"] == "final"
    assert result.payload["summary"] == "Done"

    events = _read_runlog(result.run_dir)
    # The finish_task tool_result must indicate task_completed (no error).
    finish_results = [
        e for e in events
        if e["kind"] == "tool_result" and e["payload"]["tool"] == "finish_task"
    ]
    assert len(finish_results) == 1
    assert finish_results[0]["payload"]["result"] == {"status": "task_completed"}


@pytest.mark.asyncio
async def test_finish_task_valid_args_includes_all_provided_fields(tmp_path):
    """All fields provided to finish_task are present in the RunResult payload."""
    result = await _run(
        [
            _tool_response("list_files", call_id="c0"),
            _finish_response(call_id="c1", summary="Created API", artifacts=["app.py"], notes="run with uvicorn"),
        ],
        tmp_path=tmp_path,
    )
    assert result.payload["summary"] == "Created API"
    assert result.payload["artifacts"] == ["app.py"]
    assert result.payload["notes"] == "run with uvicorn"


@pytest.mark.asyncio
async def test_finish_task_research_pack_requires_executive_summary(tmp_path):
    """Research pack's required field is 'executive_summary', not 'summary'."""
    prior_tool = _tool_response("list_files", call_id="c0")
    # Missing executive_summary → should be rejected.
    incomplete = LLMResponse(
        content=None,
        tool_calls=[ToolCallRequest(
            call_id="c1",
            tool_name="finish_task",
            arguments={"key_findings": ["finding"]},
        )],
    )
    valid_call = LLMResponse(
        content=None,
        tool_calls=[ToolCallRequest(
            call_id="c2",
            tool_name="finish_task",
            arguments={
                "executive_summary": "Overview",
                "key_findings": ["finding"],
                "citations": [],
                "gaps_and_future_work": [],
            },
        )],
    )

    result = await _run([prior_tool, incomplete, valid_call], tmp_path=tmp_path, specialist_id="research")

    assert result.payload["action"] == "final"
    assert result.payload["executive_summary"] == "Overview"

    events = _read_runlog(result.run_dir)
    error_result = next(
        e for e in events
        if e["kind"] == "tool_result"
        and e["payload"]["tool"] == "finish_task"
        and "missing_fields" in e["payload"].get("result", {})
    )
    assert "executive_summary" in error_result["payload"]["result"]["missing_fields"]


# ---------------------------------------------------------------------------
# Structural quality gate: finish_task requires prior tool call
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_finish_task_without_prior_tool_call_is_rejected(tmp_path):
    """finish_task called before any other tool is rejected; the LLM is asked to do work first."""
    # Step 0: finish_task immediately (no prior tool) → blocked
    # Step 1: list_files → any_non_finish_tool_called = True
    # Step 2: finish_task → accepted
    premature_finish = _finish_response(call_id="c1")
    prior_tool = _tool_response("list_files", call_id="c2")
    valid_finish = _finish_response(call_id="c3")

    result = await _run([premature_finish, prior_tool, valid_finish], tmp_path=tmp_path)

    assert result.payload["action"] == "final"

    events = _read_runlog(result.run_dir)
    # The premature finish must produce the "no work done" error.
    no_work_errors = [
        e for e in events
        if e["kind"] == "tool_result"
        and e["payload"]["tool"] == "finish_task"
        and e["payload"].get("result", {}).get("error") == "finish_task_called_without_doing_work"
    ]
    assert len(no_work_errors) == 1

    # Three LLM calls: premature finish (rejected), list_files, valid finish.
    llm_requests = [e for e in events if e["kind"] == "llm_request"]
    assert len(llm_requests) == 3


@pytest.mark.asyncio
async def test_finish_task_allowed_after_failed_tool_call(tmp_path):
    """A tool that raises an exception still counts as 'attempted'; finish_task is allowed afterward."""
    # list_files will raise (mocked to fail), but any_non_finish_tool_called is still set True.
    responses = [_tool_response("list_files", call_id="c1"), _finish_response(call_id="c2")]
    with _patch_execute_tool(OSError("disk full")):
        result = await _run(responses, tmp_path=tmp_path)

    assert result.payload["action"] == "final"
    events = _read_runlog(result.run_dir)
    # The failed list_files should produce a tool_error (not tool_result).
    assert any(e["kind"] == "tool_error" for e in events)
    # finish_task should succeed (no "no work done" error).
    no_work_errors = [
        e for e in events
        if e["kind"] == "tool_result"
        and e["payload"].get("result", {}).get("error") == "finish_task_called_without_doing_work"
    ]
    assert len(no_work_errors) == 0


# ---------------------------------------------------------------------------
# Plain-text (no tool calls) response
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_plain_text_response_produces_final_payload(tmp_path):
    """If the LLM returns plain text with no tool calls, it becomes the final payload."""
    plain_response = LLMResponse(content="I have completed the task.", tool_calls=[])

    result = await _run([plain_response], tmp_path=tmp_path)

    assert result.payload["action"] == "final"
    assert result.payload["summary"] == "I have completed the task."
    assert "notes" in result.payload  # fallback note must be present
    assert "finish_task" in result.payload["notes"]


@pytest.mark.asyncio
async def test_plain_text_empty_content_produces_empty_summary(tmp_path):
    """Plain-text response with None content produces an empty summary (not a crash)."""
    result = await _run([LLMResponse(content=None, tool_calls=[])], tmp_path=tmp_path)

    assert result.payload["action"] == "final"
    assert result.payload["summary"] == ""


# ---------------------------------------------------------------------------
# max_steps exhaustion
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_max_steps_exceeded_returns_timeout_payload(tmp_path):
    """When max_steps is reached without finish_task, a timeout payload is returned."""
    # Always returns a list_files call — never finishes.
    looping_response = _tool_response("list_files", call_id="c1")

    result = await _run(
        [looping_response] * 5,  # more than max_steps=3
        tmp_path=tmp_path,
        max_steps=3,
    )

    assert result.payload["action"] == "final"
    assert "max_steps" in result.payload["summary"].lower() or "3" in result.payload["summary"]
    assert result.payload.get("next_steps")

    events = _read_runlog(result.run_dir)
    llm_requests = [e for e in events if e["kind"] == "llm_request"]
    assert len(llm_requests) == 3


@pytest.mark.asyncio
async def test_max_steps_runlog_has_expected_event_count(tmp_path):
    """Each step produces exactly one llm_request and one llm_response event."""
    looping_response = _tool_response("list_files", call_id="c1")

    result = await _run([looping_response] * 5, tmp_path=tmp_path, max_steps=2)

    events = _read_runlog(result.run_dir)
    assert len([e for e in events if e["kind"] == "llm_request"]) == 2
    assert len([e for e in events if e["kind"] == "llm_response"]) == 2


# ---------------------------------------------------------------------------
# Tool error classification (T1-2)
# ---------------------------------------------------------------------------

def _patch_execute_tool(exc: Exception):
    """Context manager: make BaseSpecialistPack.execute_tool raise ``exc``."""
    return patch.object(BaseSpecialistPack, "execute_tool", side_effect=exc)


async def _run_with_tool_error(exc: Exception, tmp_path) -> tuple[dict, list[dict]]:
    """Run a two-step task: first call triggers a tool error, second call finishes."""
    responses = [
        _tool_response("list_files", call_id="c1"),
        _finish_response(call_id="c2"),
    ]
    with _patch_execute_tool(exc):
        result = await _run(responses, tmp_path=tmp_path)
    return result, _read_runlog(result.run_dir)


@pytest.mark.asyncio
async def test_permission_error_produces_tool_error_event(tmp_path):
    """PermissionError (sandbox violation) is logged as tool_error with error_type='permission'."""
    result, events = await _run_with_tool_error(
        PermissionError("Path must be within sandbox root"), tmp_path
    )

    tool_errors = [e for e in events if e["kind"] == "tool_error"]
    assert len(tool_errors) == 1
    assert tool_errors[0]["payload"]["error_type"] == "permission"
    assert tool_errors[0]["payload"]["tool"] == "list_files"
    assert "sandbox" in tool_errors[0]["payload"]["error_message"].lower()

    # No tool_result for the failed tool; only a tool_result for finish_task.
    tool_results = [e for e in events if e["kind"] == "tool_result"]
    finish_results = [e for e in tool_results if e["payload"]["tool"] == "finish_task"]
    list_results = [e for e in tool_results if e["payload"]["tool"] == "list_files"]
    assert len(finish_results) == 1
    assert len(list_results) == 0

    # Loop continues after the error; task finishes successfully.
    assert result.payload["action"] == "final"


@pytest.mark.asyncio
async def test_value_error_produces_tool_error_event(tmp_path):
    """ValueError (bad LLM arguments) is logged as tool_error with error_type='invalid_args'."""
    result, events = await _run_with_tool_error(
        ValueError("cmd must be a non-empty list"), tmp_path
    )

    tool_errors = [e for e in events if e["kind"] == "tool_error"]
    assert len(tool_errors) == 1
    assert tool_errors[0]["payload"]["error_type"] == "invalid_args"
    assert result.payload["action"] == "final"


@pytest.mark.asyncio
async def test_type_error_produces_tool_error_event(tmp_path):
    """TypeError (wrong argument type from LLM) is logged as tool_error with error_type='invalid_args'."""
    result, events = await _run_with_tool_error(
        TypeError("expected list, got str"), tmp_path
    )

    tool_errors = [e for e in events if e["kind"] == "tool_error"]
    assert len(tool_errors) == 1
    assert tool_errors[0]["payload"]["error_type"] == "invalid_args"
    assert result.payload["action"] == "final"


@pytest.mark.asyncio
async def test_os_error_produces_tool_error_event(tmp_path):
    """OSError (filesystem error) is logged as tool_error with error_type='io_error'."""
    result, events = await _run_with_tool_error(
        OSError("No space left on device"), tmp_path
    )

    tool_errors = [e for e in events if e["kind"] == "tool_error"]
    assert len(tool_errors) == 1
    assert tool_errors[0]["payload"]["error_type"] == "io_error"
    assert result.payload["action"] == "final"


@pytest.mark.asyncio
async def test_unexpected_error_produces_tool_error_event(tmp_path):
    """Unexpected exception is logged as tool_error with error_type='unexpected' (not raised)."""
    result, events = await _run_with_tool_error(
        RuntimeError("something completely unexpected"), tmp_path
    )

    tool_errors = [e for e in events if e["kind"] == "tool_error"]
    assert len(tool_errors) == 1
    assert tool_errors[0]["payload"]["error_type"] == "unexpected"
    # Error message includes the original message.
    assert "unexpected" in tool_errors[0]["payload"]["error_message"].lower()
    assert result.payload["action"] == "final"


@pytest.mark.asyncio
async def test_error_content_sent_to_llm_as_tool_result_message(tmp_path):
    """The error dict is sent back to the LLM (as a tool message) so it can adapt."""
    # We can verify this indirectly: the LLM is called a second time (it received
    # the error and produced a finish_task response).
    result, events = await _run_with_tool_error(
        PermissionError("path escape"), tmp_path
    )

    llm_requests = [e for e in events if e["kind"] == "llm_request"]
    assert len(llm_requests) == 2, (
        "LLM must be called twice: once to get list_files, once after receiving the error"
    )


@pytest.mark.asyncio
async def test_successful_tool_produces_tool_result_not_tool_error(tmp_path):
    """Successful tool execution produces tool_result; no tool_error event must be present."""
    result = await _run(
        [_tool_response("list_files", call_id="c1"), _finish_response(call_id="c2")],
        tmp_path=tmp_path,
    )
    events = _read_runlog(result.run_dir)

    assert not any(e["kind"] == "tool_error" for e in events)
    list_results = [
        e for e in events
        if e["kind"] == "tool_result" and e["payload"]["tool"] == "list_files"
    ]
    assert len(list_results) == 1


# ---------------------------------------------------------------------------
# Additional coverage (T2-3)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_malformed_tool_arguments_produce_tool_error(tmp_path):
    """When the LLM returns unparseable JSON, the client stores {'_raw': '...'}.
    The tool receives unexpected kwargs → TypeError → tool_error event, loop continues.
    """
    # Simulate the _raw fallback that client.py produces on json.JSONDecodeError.
    # The LLM response with _raw args triggers a TypeError in the tool → tool_error event.
    result, events = await _run_with_tool_error(TypeError("unexpected keyword argument '_raw'"), tmp_path)

    # tool_error must be logged (TypeError → invalid_args)
    tool_errors = [e for e in events if e["kind"] == "tool_error"]
    assert len(tool_errors) == 1
    assert tool_errors[0]["payload"]["error_type"] == "invalid_args"
    # Loop continued past the error; task completed.
    assert result.payload["action"] == "final"


@pytest.mark.asyncio
async def test_multiple_tool_calls_in_one_response_all_processed(tmp_path):
    """When the LLM returns two tool calls in one response, both are executed."""
    multi_tool_response = LLMResponse(
        content=None,
        tool_calls=[
            ToolCallRequest(call_id="c1", tool_name="list_files", arguments={}),
            ToolCallRequest(call_id="c2", tool_name="list_files", arguments={}),
        ],
    )
    result = await _run(
        [multi_tool_response, _finish_response(call_id="c3")],
        tmp_path=tmp_path,
    )
    events = _read_runlog(result.run_dir)

    # Both tool calls should produce tool_result events in step_0.
    step0_results = [
        e for e in events
        if e["kind"] == "tool_result" and e.get("step") == "step_0"
        and e["payload"]["tool"] == "list_files"
    ]
    assert len(step0_results) == 2, "Both list_files calls should produce tool_result events"
    assert result.payload["action"] == "final"


@pytest.mark.asyncio
async def test_finish_task_coexisting_with_regular_tool_in_same_response(tmp_path):
    """If the LLM returns finish_task alongside a regular tool in one response,
    the regular tool is still executed and finish_task terminates the run.
    """
    combined_response = LLMResponse(
        content=None,
        tool_calls=[
            ToolCallRequest(call_id="c1", tool_name="list_files", arguments={}),
            ToolCallRequest(
                call_id="c2",
                tool_name="finish_task",
                arguments={"summary": "Done", "artifacts": [], "next_steps": [], "notes": ""},
            ),
        ],
    )
    result = await _run([combined_response], tmp_path=tmp_path)

    assert result.payload["action"] == "final"
    assert result.payload["summary"] == "Done"

    events = _read_runlog(result.run_dir)
    # The regular tool should have produced a tool_result.
    list_results = [
        e for e in events
        if e["kind"] == "tool_result" and e["payload"]["tool"] == "list_files"
    ]
    assert len(list_results) == 1
    # Exactly one LLM call (no retry needed).
    assert len([e for e in events if e["kind"] == "llm_request"]) == 1


@pytest.mark.asyncio
async def test_unknown_tool_name_returns_error_dict_to_llm(tmp_path):
    """Calling a tool that doesn't exist in the pack returns an error dict to the
    LLM (not a tool_error event) — execute_tool handles it without raising.
    """
    unknown_tool_call = LLMResponse(
        content=None,
        tool_calls=[ToolCallRequest(call_id="c1", tool_name="does_not_exist", arguments={})],
    )
    result = await _run([unknown_tool_call, _finish_response(call_id="c2")], tmp_path=tmp_path)

    events = _read_runlog(result.run_dir)
    # No tool_error — execute_tool returns an error dict, not an exception.
    assert not any(e["kind"] == "tool_error" for e in events)
    # The error dict is logged as a tool_result.
    tool_results = [
        e for e in events
        if e["kind"] == "tool_result" and e["payload"]["tool"] == "does_not_exist"
    ]
    assert len(tool_results) == 1
    assert "error" in tool_results[0]["payload"]["result"]
    # Loop continued; task completed.
    assert result.payload["action"] == "final"


# ---------------------------------------------------------------------------
# Security events (T2-4)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_permission_error_produces_security_event(tmp_path):
    """PermissionError produces both a tool_error AND a security_event in the runlog."""
    result, events = await _run_with_tool_error(
        PermissionError("path escape: /etc/passwd outside sandbox root"), tmp_path
    )

    security_events = [e for e in events if e["kind"] == "security_event"]
    assert len(security_events) == 1, "Exactly one security_event must be logged"

    sec = security_events[0]["payload"]
    assert sec["event_type"] == "sandbox_violation"
    assert sec["tool"] == "list_files"
    assert "/etc/passwd" in sec["error_message"]


@pytest.mark.asyncio
async def test_security_event_accompanies_tool_error(tmp_path):
    """The security_event is emitted alongside (not instead of) the tool_error event."""
    result, events = await _run_with_tool_error(
        PermissionError("path escape"), tmp_path
    )

    tool_errors = [e for e in events if e["kind"] == "tool_error"]
    security_events = [e for e in events if e["kind"] == "security_event"]
    assert len(tool_errors) == 1
    assert len(security_events) == 1
    # Both events reference the same tool and step.
    assert tool_errors[0]["payload"]["tool"] == security_events[0]["payload"]["tool"]
    assert tool_errors[0].get("step") == security_events[0].get("step")


@pytest.mark.asyncio
async def test_non_permission_errors_produce_no_security_event(tmp_path):
    """ValueError, OSError, and unexpected errors do NOT produce security_event entries."""
    for exc in [ValueError("bad args"), OSError("disk full"), RuntimeError("oops")]:
        result, events = await _run_with_tool_error(exc, tmp_path)
        assert not any(e["kind"] == "security_event" for e in events), (
            f"security_event must not be emitted for {type(exc).__name__}"
        )
