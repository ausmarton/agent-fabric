"""Unit tests for LLM-driven routing: llm_recruit_specialist.

All tests use AsyncMock to patch OllamaChatClient.chat so no real LLM is
invoked. The tests verify routing logic, fallback behaviour, and the
routing_method field of the returned RecruitmentResult.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agent_fabric.application.recruit import llm_recruit_specialist
from agent_fabric.config import DEFAULT_CONFIG
from agent_fabric.domain import LLMResponse, ToolCallRequest
from agent_fabric.infrastructure.ollama import OllamaChatClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _routing_resp(capabilities: list[str], reasoning: str = "test") -> LLMResponse:
    """Build a mock LLM response that calls select_capabilities."""
    return LLMResponse(
        content=None,
        tool_calls=[ToolCallRequest(
            call_id="r0",
            tool_name="select_capabilities",
            arguments={"capabilities": capabilities, "reasoning": reasoning},
        )],
    )


async def _call_llm_recruit(mock_response: LLMResponse, prompt: str) -> object:
    """Invoke llm_recruit_specialist with a patched chat client."""
    with patch.object(
        OllamaChatClient, "chat", new_callable=AsyncMock, return_value=mock_response
    ):
        client = OllamaChatClient(base_url="http://localhost:11434/v1", timeout_s=5.0)
        return await llm_recruit_specialist(
            prompt,
            DEFAULT_CONFIG,
            chat_client=client,
            model="llama3.1:8b",
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_routing_selects_engineering():
    """caps=[code_execution] → engineering pack selected."""
    result = await _call_llm_recruit(
        _routing_resp(["code_execution"]),
        "build a Python microservice",
    )
    assert result.specialist_ids == ["engineering"]
    assert result.routing_method == "llm_routing"


@pytest.mark.asyncio
async def test_llm_routing_selects_research():
    """caps=[systematic_review] → research pack selected."""
    result = await _call_llm_recruit(
        _routing_resp(["systematic_review"]),
        "do a literature survey on transformer models",
    )
    assert result.specialist_ids == ["research"]
    assert result.routing_method == "llm_routing"


@pytest.mark.asyncio
async def test_llm_routing_selects_task_force():
    """caps=[code_execution, systematic_review] → both packs selected."""
    result = await _call_llm_recruit(
        _routing_resp(["code_execution", "systematic_review"]),
        "build a tool that does a systematic review of arxiv papers",
    )
    assert "engineering" in result.specialist_ids
    assert "research" in result.specialist_ids
    assert result.routing_method == "llm_routing"


@pytest.mark.asyncio
async def test_llm_routing_task_force_is_in_config_order():
    """Task force specialist_ids follow config insertion order (engineering before research)."""
    result = await _call_llm_recruit(
        # Reversed cap order — result must still be config order.
        _routing_resp(["systematic_review", "code_execution"]),
        "build a tool that does a systematic review of arxiv papers",
    )
    assert result.specialist_ids.index("engineering") < result.specialist_ids.index("research")


@pytest.mark.asyncio
async def test_llm_routing_unknown_caps_filtered():
    """Unknown capability IDs are silently filtered; known ones still route correctly."""
    result = await _call_llm_recruit(
        _routing_resp(["unknown_cap", "code_execution"]),
        "build a service",
    )
    assert result.specialist_ids == ["engineering"]
    assert result.routing_method == "llm_routing"
    assert "unknown_cap" not in result.required_capabilities
    assert "code_execution" in result.required_capabilities


@pytest.mark.asyncio
async def test_llm_routing_fallback_on_no_tool_call():
    """When LLM returns plain content (no tool calls), fall back to keyword routing.

    routing_method is inherited from recruit_specialist(); for this prompt capability
    matching succeeds so it returns "keyword_routing".
    """
    no_tool_response = LLMResponse(content="engineering", tool_calls=[])
    result = await _call_llm_recruit(
        no_tool_response,
        "build a Python service",
    )
    assert len(result.specialist_ids) >= 1
    assert result.routing_method == "keyword_routing"


@pytest.mark.asyncio
async def test_llm_routing_fallback_on_exception():
    """When chat_client.chat raises, fall back to keyword routing."""
    with patch.object(
        OllamaChatClient, "chat", new_callable=AsyncMock,
        side_effect=RuntimeError("connection error"),
    ):
        client = OllamaChatClient(base_url="http://localhost:11434/v1", timeout_s=5.0)
        result = await llm_recruit_specialist(
            "build a Python service",
            DEFAULT_CONFIG,
            chat_client=client,
            model="llama3.1:8b",
        )
    assert len(result.specialist_ids) >= 1
    assert result.routing_method == "keyword_routing"


@pytest.mark.asyncio
async def test_llm_routing_fallback_empty_caps():
    """When LLM returns an empty capabilities list, fall back to keyword routing."""
    result = await _call_llm_recruit(
        _routing_resp([]),
        "build a Python service",
    )
    assert len(result.specialist_ids) >= 1
    assert result.routing_method == "keyword_routing"


@pytest.mark.asyncio
async def test_routing_method_is_llm_routing_on_success():
    """Successful LLM routing sets routing_method to 'llm_routing'."""
    result = await _call_llm_recruit(
        _routing_resp(["code_execution"]),
        "implement a REST API",
    )
    assert result.routing_method == "llm_routing"


@pytest.mark.asyncio
async def test_routing_method_is_keyword_routing_on_fallback():
    """Fallback routing_method is propagated from recruit_specialist(), not hardcoded.

    For this prompt ("pipeline", "scala" → code_execution capability match),
    recruit_specialist returns "keyword_routing". A prompt that only matches the
    hardcoded heuristic would return "keyword_fallback" instead.
    """
    no_tool_response = LLMResponse(content="I'll pick engineering", tool_calls=[])
    result = await _call_llm_recruit(
        no_tool_response,
        "write a data pipeline in Scala",
    )
    assert result.routing_method == "keyword_routing"


@pytest.mark.asyncio
async def test_fallback_propagates_keyword_fallback_method():
    """When the inner recruit_specialist() hits the hardcoded heuristic, routing_method
    is 'keyword_fallback' — not overridden to 'keyword_routing'.

    A prompt with no capability keywords and no specialist keywords triggers
    the hardcoded fallback path in recruit_specialist().
    """
    no_tool_response = LLMResponse(content="I give up", tool_calls=[])
    # "something" matches no capability keywords and no specialist keywords —
    # but does not contain code/build/implement/service/pipeline/deploy so it
    # falls to the research default. Either way the method must be 'keyword_fallback'.
    result = await _call_llm_recruit(
        no_tool_response,
        "something completely unrelated to any keyword",
    )
    assert result.routing_method == "keyword_fallback"
