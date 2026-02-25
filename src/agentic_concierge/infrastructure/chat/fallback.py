"""Cloud LLM fallback client (P6-4).

``FallbackChatClient`` wraps a *local* chat client and a *cloud* chat client.
For each call it:

1. Calls the local model.
2. Evaluates the response with the configured ``FallbackPolicy``.
3. If the policy triggers: re-calls the same prompt against the cloud model
   and records the fallback event so the caller can log it.
4. Returns whichever response was used.

The ``ChatClient`` protocol is satisfied unchanged — callers see a single
``chat()`` method.  Any pending ``cloud_fallback`` events can be drained
with ``pop_events()``, which is checked by ``_execute_pack_loop`` in
``execute_task.py``.

Policy trigger conditions (``FallbackPolicy.mode``)::

    "no_tool_calls"   — local returned plain text with no tool calls.
    "malformed_args"  — at least one tool call has {"_raw": ...} arguments
                        (the parser's fallback for unparseable JSON).
    "always"          — always use cloud (debugging / forced routing).
    <anything else>   — never trigger (no fallback); safe default.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from agentic_concierge.domain import LLMResponse

logger = logging.getLogger(__name__)


class FallbackPolicy:
    """Evaluates an LLMResponse and returns a reason string if the cloud fallback
    should be used, or ``None`` if the local response is acceptable.

    Args:
        mode: Trigger condition.  One of ``"no_tool_calls"``, ``"malformed_args"``,
              ``"always"``.  Unknown values always return ``None`` (no trigger).
    """

    def __init__(self, mode: str) -> None:
        self._mode = mode

    @property
    def mode(self) -> str:
        return self._mode

    def evaluate(self, response: LLMResponse) -> Optional[str]:
        """Return a reason string if the policy triggers, else ``None``."""
        if self._mode == "no_tool_calls":
            if not response.has_tool_calls:
                return "no_tool_calls"

        elif self._mode == "malformed_args":
            for tc in response.tool_calls:
                if "_raw" in tc.arguments:
                    return "malformed_args"

        elif self._mode == "always":
            return "always"

        # Unknown mode or response is acceptable.
        return None


class FallbackChatClient:
    """Chat client that falls back to a cloud model when the local response
    fails the quality policy.

    Satisfies the ``ChatClient`` protocol (has a ``chat()`` async method).

    Additionally exposes ``pop_events()`` so ``_execute_pack_loop`` can drain
    pending ``cloud_fallback`` runlog events after each LLM call.

    Args:
        local: Local ``ChatClient`` (tried first).
        cloud: Cloud ``ChatClient`` (used when policy triggers).
        cloud_model: Model name to pass to the cloud client's ``chat()`` method.
        policy: ``FallbackPolicy`` instance.
    """

    def __init__(
        self,
        local: Any,
        cloud: Any,
        cloud_model: str,
        policy: FallbackPolicy,
    ) -> None:
        self._local = local
        self._cloud = cloud
        self._cloud_model = cloud_model
        self._policy = policy
        self._pending_events: List[Dict[str, Any]] = []

    def pop_events(self) -> List[Dict[str, Any]]:
        """Drain and return any pending cloud_fallback events.

        Each event is a dict with ``reason``, ``local_model``, ``cloud_model``.
        The internal queue is cleared on each call.
        """
        events, self._pending_events = self._pending_events, []
        return events

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
        """Call the local model; fall back to cloud if the policy triggers."""
        kwargs = dict(
            tools=tools,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
        )

        local_response = await self._local.chat(messages, model, **kwargs)

        reason = self._policy.evaluate(local_response)
        if reason is None:
            return local_response

        logger.info(
            "Cloud fallback triggered: reason=%s local_model=%s cloud_model=%s",
            reason, model, self._cloud_model,
        )

        cloud_response = await self._cloud.chat(messages, self._cloud_model, **kwargs)

        self._pending_events.append({
            "reason": reason,
            "local_model": model,
            "cloud_model": self._cloud_model,
        })

        return cloud_response
