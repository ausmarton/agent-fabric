"""Tests for infrastructure/chat/inprocess.py — InProcessChatClient.

The mistralrs wheel is not installed in the test environment, so we mock
``sys.modules`` to simulate its presence or absence.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from agentic_concierge.config.features import Feature, FeatureDisabledError
from agentic_concierge.infrastructure.chat.inprocess import InProcessChatClient, is_available


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------

def test_is_available_false_when_not_installed():
    with patch("importlib.util.find_spec", return_value=None):
        assert is_available() is False


def test_is_available_true_when_installed():
    with patch("importlib.util.find_spec", return_value=MagicMock()):
        assert is_available() is True


# ---------------------------------------------------------------------------
# InProcessChatClient instantiation
# ---------------------------------------------------------------------------

def test_init_raises_when_mistralrs_absent():
    with patch("importlib.util.find_spec", return_value=None):
        with pytest.raises(FeatureDisabledError) as exc_info:
            InProcessChatClient(model_path="/tmp/model.gguf")
    assert exc_info.value.feature == Feature.INPROCESS
    assert "nano" in str(exc_info.value)


def test_init_succeeds_when_mistralrs_present():
    with patch("importlib.util.find_spec", return_value=MagicMock()):
        client = InProcessChatClient(model_path="/tmp/model.gguf")
    assert client.model_path == "/tmp/model.gguf"
    assert client._engine is None  # lazy


# ---------------------------------------------------------------------------
# chat — mocked mistralrs
# ---------------------------------------------------------------------------

def _make_mistralrs_mock(content: str = "", tool_calls=None):
    """Build a fake mistralrs module with the minimal API we use."""
    mock_fn = MagicMock()
    mock_fn.name = "write_file"
    mock_fn.arguments = '{"path": "f.txt"}'

    mock_tc = MagicMock()
    mock_tc.id = "call_1"
    mock_tc.function = mock_fn

    mock_msg = MagicMock()
    mock_msg.content = content
    mock_msg.tool_calls = tool_calls or []

    mock_choice = MagicMock()
    mock_choice.message = mock_msg

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    mock_engine = MagicMock()
    mock_engine.send_chat_completion_request.return_value = mock_response

    mock_runner_cls = MagicMock(return_value=mock_engine)

    mock_module = MagicMock()
    mock_module.Runner = mock_runner_cls
    mock_module.Which = MagicMock()
    mock_module.Which.Gguf = MagicMock()
    mock_module.ChatCompletionRequest = MagicMock(return_value=MagicMock())
    return mock_module


@pytest.mark.asyncio
async def test_chat_plain_text():
    mistralrs_mock = _make_mistralrs_mock(content="Answer!")
    with (
        patch("importlib.util.find_spec", return_value=MagicMock()),
        patch.dict(sys.modules, {"mistralrs": mistralrs_mock}),
    ):
        client = InProcessChatClient(model_path="/model.gguf")
        result = await client.chat(
            messages=[{"role": "user", "content": "Hi"}],
            model="qwen2.5:0.5b",
        )
    assert result.content == "Answer!"
    assert result.tool_calls == []


@pytest.mark.asyncio
async def test_chat_tool_call_parsed():
    tc_mock = MagicMock()
    tc_mock.id = "call_abc"
    tc_mock.function = MagicMock()
    tc_mock.function.name = "shell"
    tc_mock.function.arguments = '{"cmd": ["ls"]}'

    mistralrs_mock = _make_mistralrs_mock(tool_calls=[tc_mock])
    with (
        patch("importlib.util.find_spec", return_value=MagicMock()),
        patch.dict(sys.modules, {"mistralrs": mistralrs_mock}),
    ):
        client = InProcessChatClient(model_path="/model.gguf")
        result = await client.chat(
            messages=[{"role": "user", "content": "run ls"}],
            model="qwen2.5:0.5b",
            tools=[{"type": "function", "function": {"name": "shell"}}],
        )
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].tool_name == "shell"
    assert result.tool_calls[0].arguments == {"cmd": ["ls"]}


@pytest.mark.asyncio
async def test_chat_tool_call_malformed_json_args():
    tc_mock = MagicMock()
    tc_mock.id = "call_x"
    tc_mock.function = MagicMock()
    tc_mock.function.name = "write_file"
    tc_mock.function.arguments = "NOT JSON"

    mistralrs_mock = _make_mistralrs_mock(tool_calls=[tc_mock])
    with (
        patch("importlib.util.find_spec", return_value=MagicMock()),
        patch.dict(sys.modules, {"mistralrs": mistralrs_mock}),
    ):
        client = InProcessChatClient(model_path="/model.gguf")
        result = await client.chat(
            messages=[{"role": "user", "content": "do it"}],
            model="qwen2.5:0.5b",
        )
    assert result.tool_calls[0].arguments == {"_raw": "NOT JSON"}


@pytest.mark.asyncio
async def test_engine_lazy_loaded():
    mistralrs_mock = _make_mistralrs_mock(content="ok")
    with (
        patch("importlib.util.find_spec", return_value=MagicMock()),
        patch.dict(sys.modules, {"mistralrs": mistralrs_mock}),
    ):
        client = InProcessChatClient(model_path="/model.gguf")
        assert client._engine is None
        await client.chat(
            messages=[{"role": "user", "content": "hi"}], model="m"
        )
        assert client._engine is not None  # loaded after first call
