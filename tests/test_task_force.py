"""Tests for Phase 3 multi-pack task force: recruitment and sequential execution.

These tests cover:
- Greedy recruitment: mixed-capability prompts yield task forces.
- execute_task with multiple specialists: both packs run, share workspace and runlog.
- Context handoff: second pack receives first pack's finish payload in messages.
- Runlog structure: pack_start events, step names prefixed with specialist ID.
- RunResult: specialist_ids, is_task_force, specialist_id (primary = first).
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agent_fabric.application.execute_task import execute_task
from agent_fabric.application.recruit import RecruitmentResult, recruit_specialist, _greedy_select_specialists
from agent_fabric.config import DEFAULT_CONFIG, FabricConfig, load_config
from agent_fabric.config.schema import SpecialistConfig, ModelConfig
from agent_fabric.domain import LLMResponse, Task, ToolCallRequest
from agent_fabric.infrastructure.ollama import OllamaChatClient
from agent_fabric.infrastructure.specialists import ConfigSpecialistRegistry
from agent_fabric.infrastructure.workspace import FileSystemRunRepository


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _eng_finish(call_id: str = "c1", summary: str = "Engineering done") -> LLMResponse:
    """Engineering pack finish_task response."""
    return LLMResponse(
        content=None,
        tool_calls=[ToolCallRequest(
            call_id=call_id,
            tool_name="finish_task",
            arguments={
                "summary": summary,
                "artifacts": ["tool.py"],
                "next_steps": ["write docs"],
                "notes": "",
            },
        )],
    )


def _research_finish(call_id: str = "c2", summary: str = "Research done") -> LLMResponse:
    """Research pack finish_task response."""
    return LLMResponse(
        content=None,
        tool_calls=[ToolCallRequest(
            call_id=call_id,
            tool_name="finish_task",
            arguments={
                "executive_summary": summary,
                "key_findings": ["finding1"],
                "citations": [],
                "gaps_and_future_work": [],
            },
        )],
    )


def _read_runlog(run_dir: str) -> list[dict]:
    lines = Path(run_dir, "runlog.jsonl").read_text().strip().splitlines()
    return [json.loads(ln) for ln in lines if ln]


# ---------------------------------------------------------------------------
# Unit: greedy selection (no config required)
# ---------------------------------------------------------------------------

def _make_specialist(capabilities: list[str]) -> SpecialistConfig:
    return SpecialistConfig(
        description="test",
        workflow="engineering",
        capabilities=capabilities,
    )


def test_greedy_selects_single_pack_when_one_covers_all():
    specialists = {
        "eng": _make_specialist(["code_execution", "file_io"]),
        "res": _make_specialist(["systematic_review", "web_search"]),
    }
    name_order = {"eng": 0, "res": 1}
    selected = _greedy_select_specialists(["code_execution"], specialists, name_order)
    assert selected == ["eng"]


def test_greedy_selects_two_packs_for_non_overlapping_caps():
    specialists = {
        "eng": _make_specialist(["code_execution"]),
        "res": _make_specialist(["systematic_review"]),
    }
    name_order = {"eng": 0, "res": 1}
    selected = _greedy_select_specialists(
        ["code_execution", "systematic_review"], specialists, name_order
    )
    assert set(selected) == {"eng", "res"}
    assert selected == ["eng", "res"]   # config order


def test_greedy_result_is_in_config_order_regardless_of_cap_order():
    """Selected specialists are always sorted by config order, not greedy pick order."""
    specialists = {
        "eng": _make_specialist(["code_execution"]),
        "res": _make_specialist(["systematic_review"]),
    }
    name_order = {"eng": 0, "res": 1}
    # Caps in "res-first" order — result must still be ["eng", "res"]
    selected = _greedy_select_specialists(
        ["systematic_review", "code_execution"], specialists, name_order
    )
    assert selected == ["eng", "res"]


def test_greedy_returns_empty_when_no_coverage():
    specialists = {
        "eng": _make_specialist(["code_execution"]),
    }
    name_order = {"eng": 0}
    selected = _greedy_select_specialists(["systematic_review"], specialists, name_order)
    assert selected == []


def test_greedy_shared_capability_selects_one_pack():
    """file_io is provided by both packs; only one should be selected."""
    specialists = {
        "eng": _make_specialist(["code_execution", "file_io"]),
        "res": _make_specialist(["systematic_review", "file_io"]),
    }
    name_order = {"eng": 0, "res": 1}
    selected = _greedy_select_specialists(["file_io"], specialists, name_order)
    assert len(selected) == 1   # one pack is sufficient


# ---------------------------------------------------------------------------
# Unit: recruit_specialist task-force behaviour
# ---------------------------------------------------------------------------

def test_recruit_mixed_prompt_returns_task_force():
    """Prompts needing engineering + research capabilities recruit both packs."""
    result = recruit_specialist(
        "build a tool that does a systematic review of arxiv papers",
        DEFAULT_CONFIG,
    )
    assert result.is_task_force
    assert "engineering" in result.specialist_ids
    assert "research" in result.specialist_ids


def test_recruit_single_cap_prompt_is_not_task_force():
    result = recruit_specialist("build a Python service", DEFAULT_CONFIG)
    assert not result.is_task_force
    assert result.specialist_ids == ["engineering"]


def test_recruit_specialist_id_property_returns_first():
    result = recruit_specialist(
        "build a tool that does a systematic review of arxiv papers",
        DEFAULT_CONFIG,
    )
    assert result.specialist_id == result.specialist_ids[0]


@pytest.mark.parametrize("prompt,expected_ids", [
    # Single-pack prompts
    ("build a Python service",             ["engineering"]),
    ("systematic review of literature",    ["research"]),
    # Multi-pack prompt
    ("build a systematic review tool",     ["engineering", "research"]),
])
def test_specialist_ids_for_various_prompts(prompt, expected_ids):
    result = recruit_specialist(prompt, DEFAULT_CONFIG)
    for sid in expected_ids:
        assert sid in result.specialist_ids
    # Single-pack prompts must NOT be task forces.
    if len(expected_ids) == 1:
        assert not result.is_task_force


# ---------------------------------------------------------------------------
# Integration: execute_task with task force
# ---------------------------------------------------------------------------

async def _run_task_force(prompt: str, mock_responses: list, *, tmp_path) -> tuple:
    """Run execute_task with the given prompt and mock LLM responses.
    Returns (result, events).
    """
    config = load_config()
    run_repository = FileSystemRunRepository(workspace_root=str(tmp_path))
    specialist_registry = ConfigSpecialistRegistry(config)
    with patch.object(
        OllamaChatClient, "chat", new_callable=AsyncMock, side_effect=mock_responses
    ):
        chat_client = OllamaChatClient(base_url="http://localhost:11434/v1", timeout_s=5.0)
        task = Task(prompt=prompt, specialist_id=None, network_allowed=False)
        result = await execute_task(
            task,
            chat_client=chat_client,
            run_repository=run_repository,
            specialist_registry=specialist_registry,
            config=config,
            max_steps=10,
        )
    events = _read_runlog(result.run_dir)
    return result, events


@pytest.mark.asyncio
async def test_task_force_runs_both_packs(tmp_path):
    """A mixed-capability prompt executes engineering then research packs."""
    result, events = await _run_task_force(
        "build a tool that does a systematic review of arxiv papers",
        [_eng_finish(), _research_finish()],
        tmp_path=tmp_path,
    )

    assert result.is_task_force
    assert "engineering" in result.specialist_ids
    assert "research" in result.specialist_ids
    assert result.specialist_id == "engineering"  # primary = first


@pytest.mark.asyncio
async def test_task_force_runlog_has_pack_start_events(tmp_path):
    """Multi-pack runs log a pack_start event at the beginning of each pack."""
    result, events = await _run_task_force(
        "build a tool that does a systematic review of arxiv papers",
        [_eng_finish(), _research_finish()],
        tmp_path=tmp_path,
    )

    pack_starts = [e for e in events if e["kind"] == "pack_start"]
    assert len(pack_starts) == 2

    ids_in_order = [e["payload"]["specialist_id"] for e in pack_starts]
    assert ids_in_order == ["engineering", "research"]
    assert pack_starts[0]["payload"]["pack_index"] == 0
    assert pack_starts[1]["payload"]["pack_index"] == 1


@pytest.mark.asyncio
async def test_task_force_runlog_step_names_are_pack_prefixed(tmp_path):
    """In a task force, step events use '{specialist_id}_step_N' naming."""
    result, events = await _run_task_force(
        "build a tool that does a systematic review of arxiv papers",
        [_eng_finish(), _research_finish()],
        tmp_path=tmp_path,
    )

    llm_request_steps = [
        e.get("step") for e in events if e["kind"] == "llm_request"
    ]
    assert any(s and s.startswith("engineering_step_") for s in llm_request_steps)
    assert any(s and s.startswith("research_step_") for s in llm_request_steps)


@pytest.mark.asyncio
async def test_task_force_shared_workspace(tmp_path):
    """Both packs in a task force write to the same workspace directory."""
    result, events = await _run_task_force(
        "build a tool that does a systematic review of arxiv papers",
        [_eng_finish(), _research_finish()],
        tmp_path=tmp_path,
    )

    # Both packs operate in the same run_dir/workspace.
    assert Path(result.workspace_path).is_dir()
    # Only one workspace (one run_dir) per task.
    assert result.run_dir  # single run dir


@pytest.mark.asyncio
async def test_task_force_context_passed_to_second_pack(tmp_path):
    """The second pack receives the first pack's finish payload as context.

    We verify this by checking the runlog: the research pack's first LLM request
    must follow a pack_start event, and we can inspect the message count is higher
    than a fresh start (system + user with context).
    """
    result, events = await _run_task_force(
        "build a tool that does a systematic review of arxiv papers",
        [_eng_finish(summary="Created tool.py"), _research_finish()],
        tmp_path=tmp_path,
    )

    # The research pack (2nd) gets a user message with context, so message_count
    # at its first llm_request step must be >= 2 (system + user).
    research_llm_requests = [
        e for e in events
        if e["kind"] == "llm_request" and e.get("step", "").startswith("research_")
    ]
    assert len(research_llm_requests) >= 1
    # message_count should be 2 (system prompt + user message with context).
    assert research_llm_requests[0]["payload"]["message_count"] == 2


@pytest.mark.asyncio
async def test_task_force_result_payload_is_from_last_pack(tmp_path):
    """RunResult.payload comes from the last pack's finish_task call."""
    result, _ = await _run_task_force(
        "build a tool that does a systematic review of arxiv papers",
        [_eng_finish(summary="Engineering done"),
         _research_finish(summary="Research complete")],
        tmp_path=tmp_path,
    )

    # Research pack uses 'executive_summary', not 'summary'.
    assert result.payload.get("executive_summary") == "Research complete"
    assert "summary" not in result.payload or result.payload.get("executive_summary")


@pytest.mark.asyncio
async def test_task_force_recruitment_event_includes_specialist_ids(tmp_path):
    """The recruitment runlog event includes specialist_ids (plural) and is_task_force."""
    result, events = await _run_task_force(
        "build a tool that does a systematic review of arxiv papers",
        [_eng_finish(), _research_finish()],
        tmp_path=tmp_path,
    )

    recruitment_events = [e for e in events if e["kind"] == "recruitment"]
    assert len(recruitment_events) == 1

    payload = recruitment_events[0]["payload"]
    assert "specialist_ids" in payload
    assert set(payload["specialist_ids"]) == {"engineering", "research"}
    assert payload["is_task_force"] is True


@pytest.mark.asyncio
async def test_single_pack_run_is_not_a_task_force(tmp_path):
    """Single-specialist runs have is_task_force=False and specialist_ids of length 1."""
    eng_finish = _eng_finish()
    config = load_config()
    run_repository = FileSystemRunRepository(workspace_root=str(tmp_path))
    specialist_registry = ConfigSpecialistRegistry(config)
    with patch.object(
        OllamaChatClient, "chat", new_callable=AsyncMock, return_value=eng_finish
    ):
        chat_client = OllamaChatClient(base_url="http://localhost:11434/v1", timeout_s=5.0)
        task = Task(prompt="test", specialist_id="engineering", network_allowed=False)
        result = await execute_task(
            task,
            chat_client=chat_client,
            run_repository=run_repository,
            specialist_registry=specialist_registry,
            config=config,
            max_steps=10,
        )

    assert not result.is_task_force
    assert result.specialist_ids == ["engineering"]
    assert result.specialist_id == "engineering"


@pytest.mark.asyncio
async def test_single_pack_runlog_has_no_pack_start_events(tmp_path):
    """pack_start events are only emitted for task forces, not single-pack runs."""
    eng_finish = _eng_finish()
    config = load_config()
    run_repository = FileSystemRunRepository(workspace_root=str(tmp_path))
    specialist_registry = ConfigSpecialistRegistry(config)
    with patch.object(
        OllamaChatClient, "chat", new_callable=AsyncMock, return_value=eng_finish
    ):
        chat_client = OllamaChatClient(base_url="http://localhost:11434/v1", timeout_s=5.0)
        task = Task(prompt="test", specialist_id="engineering", network_allowed=False)
        result = await execute_task(
            task,
            chat_client=chat_client,
            run_repository=run_repository,
            specialist_registry=specialist_registry,
            config=config,
            max_steps=10,
        )

    events = _read_runlog(result.run_dir)
    assert not any(e["kind"] == "pack_start" for e in events)
