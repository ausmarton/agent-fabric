"""OpenAI-compatible HTTP chat client.

Default config points at Ollama (``http://localhost:11434/v1``) but any backend
exposing the same ``POST /v1/chat/completions`` endpoint works (vLLM, LiteLLM,
OpenAI, etc.).

Supports native function calling: when ``tools`` is provided the response is
parsed for ``tool_calls`` and returned as ``LLMResponse`` with structured
``ToolCallRequest`` objects, rather than raw text.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import httpx

from agent_fabric.domain import LLMResponse, ToolCallRequest


class OllamaChatClient:
    """OpenAI-compatible HTTP client with native tool-calling support.

    Sends ``POST {base_url}/chat/completions`` using the standard OpenAI
    request shape.  Falls back to a minimal payload (model + messages + stream)
    when the server returns 400, which some older Ollama versions do for unknown
    top-level parameters.
    """

    def __init__(self, base_url: str, api_key: str = "", timeout_s: float = 120.0):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout_s

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.1,
        top_p: float = 0.9,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        url = f"{self._base_url}/chat/completions"
        headers: Dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools

        timeout = httpx.Timeout(self._timeout)
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(url, headers=headers, json=payload)
            if r.status_code == 400:
                # Inspect the error body before retrying.
                err_msg = _extract_error_message(r)
                if "does not support tools" in err_msg.lower():
                    raise RuntimeError(
                        f"Model {model!r} does not support tool calling. "
                        "Use a tool-capable model such as llama3.1:8b, "
                        "mistral-small3.2:24b, or qwen2.5-coder:32b."
                    )
                # Some backends 400 on unknown top-level params (temperature,
                # top_p, …); retry with a minimal payload that still includes
                # tools (required for tool calling).
                payload_minimal: Dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "stream": False,
                }
                if tools:
                    payload_minimal["tools"] = tools
                r2 = await client.post(url, headers=headers, json=payload_minimal)
                if r2.status_code == 400:
                    err_msg2 = _extract_error_message(r2)
                    if "does not support tools" in err_msg2.lower():
                        raise RuntimeError(
                            f"Model {model!r} does not support tool calling. "
                            "Use a tool-capable model such as llama3.1:8b, "
                            "mistral-small3.2:24b, or qwen2.5-coder:32b."
                        )
                r2.raise_for_status()
                data = r2.json()
            else:
                r.raise_for_status()
                data = r.json()

        return _parse_response(data)


def _extract_error_message(response: "httpx.Response") -> str:
    """Extract a human-readable error string from a (likely 4xx) HTTP response."""
    try:
        body = response.json()
        if isinstance(body, dict):
            err = body.get("error") or {}
            if isinstance(err, dict):
                return err.get("message") or ""
            if isinstance(err, str):
                return err
    except Exception:
        pass
    return response.text or ""


def _parse_response(data: Dict[str, Any]) -> LLMResponse:
    """Parse an OpenAI-format chat completions response into an ``LLMResponse``."""
    message = data["choices"][0]["message"]
    content: Optional[str] = message.get("content")

    tool_calls: List[ToolCallRequest] = []
    for i, tc in enumerate(message.get("tool_calls") or []):
        call_id: str = tc.get("id") or f"call_{i}"
        fn = tc.get("function") or {}
        name: str = fn.get("name") or ""
        raw_args: str = fn.get("arguments") or "{}"
        try:
            arguments: Dict[str, Any] = json.loads(raw_args)
        except json.JSONDecodeError:
            arguments = {"_raw": raw_args}
        tool_calls.append(ToolCallRequest(call_id=call_id, tool_name=name, arguments=arguments))

    return LLMResponse(content=content, tool_calls=tool_calls)
