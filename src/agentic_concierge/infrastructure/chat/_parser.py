"""Shared response parser for OpenAI chat-completions responses.

Both OllamaChatClient and GenericChatClient use the same wire format; this
module keeps the parsing logic in one place so the two clients stay in sync.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from agentic_concierge.domain import LLMResponse, ToolCallRequest


def parse_chat_response(data: Dict[str, Any]) -> LLMResponse:
    """Parse an OpenAI-format chat completions response dict into ``LLMResponse``."""
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
