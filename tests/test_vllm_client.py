"""Tests for infrastructure/chat/vllm.py — VLLMChatClient."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agentic_concierge.infrastructure.chat.vllm import VLLMChatClient


def _make_response(content: str = "", tool_calls: list = None) -> dict:
    msg: dict = {"content": content, "role": "assistant"}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {"choices": [{"message": msg}]}


def _make_mock_client(response_data: dict, status: int = 200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = response_data
    resp.raise_for_status = MagicMock()
    if status >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=resp)
    mock_client.get = AsyncMock(return_value=resp)
    return mock_client


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_check_healthy():
    resp = MagicMock()
    resp.status_code = 200
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=resp)
    client = VLLMChatClient(base_url="http://localhost:8000/v1")
    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await client.health_check()
    assert result is True


@pytest.mark.asyncio
async def test_health_check_unhealthy():
    client = VLLMChatClient()
    with patch("httpx.AsyncClient.__aenter__", side_effect=httpx.ConnectError("refused")):
        result = await client.health_check()
    assert result is False


# ---------------------------------------------------------------------------
# list_models
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_models():
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"data": [{"id": "qwen2.5-7b"}, {"id": "qwen2.5-14b"}]}
    resp.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=resp)
    client = VLLMChatClient()
    with patch("httpx.AsyncClient", return_value=mock_client):
        models = await client.list_models()
    assert models == ["qwen2.5-7b", "qwen2.5-14b"]


@pytest.mark.asyncio
async def test_list_models_empty_on_error():
    client = VLLMChatClient()
    with patch("httpx.AsyncClient.__aenter__", side_effect=Exception("err")):
        models = await client.list_models()
    assert models == []


# ---------------------------------------------------------------------------
# chat — happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_chat_plain_text():
    data = _make_response(content="Hello from vLLM!")
    mock_client = _make_mock_client(data)
    client = VLLMChatClient()
    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await client.chat(
            messages=[{"role": "user", "content": "Hi"}],
            model="qwen2.5-7b",
        )
    assert result.content == "Hello from vLLM!"
    assert result.tool_calls == []


@pytest.mark.asyncio
async def test_chat_tool_call():
    data = _make_response(
        tool_calls=[{
            "id": "call_abc",
            "type": "function",
            "function": {"name": "write_file", "arguments": json.dumps({"path": "x.txt", "content": "y"})},
        }]
    )
    mock_client = _make_mock_client(data)
    client = VLLMChatClient()
    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await client.chat(
            messages=[{"role": "user", "content": "Do it"}],
            model="qwen2.5-7b",
            tools=[{"type": "function", "function": {"name": "write_file"}}],
        )
    assert len(result.tool_calls) == 1
    tc = result.tool_calls[0]
    assert tc.tool_name == "write_file"
    assert tc.arguments["path"] == "x.txt"


@pytest.mark.asyncio
async def test_chat_raises_on_non_2xx():
    mock_client = _make_mock_client({}, status=500)
    client = VLLMChatClient()
    with patch("httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(httpx.HTTPStatusError):
            await client.chat(
                messages=[{"role": "user", "content": "hi"}], model="qwen2.5-7b"
            )


@pytest.mark.asyncio
async def test_chat_sends_api_key():
    """When api_key is set, Authorization header is included."""
    data = _make_response(content="ok")
    mock_client = _make_mock_client(data)
    client = VLLMChatClient(api_key="my-secret-key")
    with patch("httpx.AsyncClient", return_value=mock_client):
        await client.chat(messages=[{"role": "user", "content": "hi"}], model="m")
    call_kwargs = mock_client.post.call_args[1]
    headers = call_kwargs.get("headers", {})
    assert headers.get("Authorization") == "Bearer my-secret-key"
