"""In-process LLM inference via mistral.rs.

Requires the ``[nano]`` extra: ``pip install 'agentic-concierge[nano]'``
which pulls in the ``mistralrs`` PyO3 wheel.

This client lazy-imports ``mistralrs`` only when instantiated so the module
can be imported freely regardless of whether the extra is installed.
"""

from __future__ import annotations

import importlib.util
import logging
from typing import Any, Dict, List, Optional

from agentic_concierge.domain import LLMResponse, ToolCallRequest

logger = logging.getLogger(__name__)


def is_available() -> bool:
    """Return ``True`` if the ``mistralrs`` package is importable.

    Uses ``importlib.util.find_spec`` so the module is not actually loaded
    when checking availability.
    """
    return importlib.util.find_spec("mistralrs") is not None


class InProcessChatClient:
    """ChatClient that runs inference in-process using mistral.rs.

    Implements the same ``chat()`` interface as the other clients.
    The mistral.rs engine is lazy-loaded on first ``chat()`` call.

    Raises:
        FeatureDisabledError: On instantiation if ``mistralrs`` is not installed.
    """

    def __init__(self, model_path: str, n_ctx: int = 4096) -> None:
        if not is_available():
            from agentic_concierge.config.features import Feature, FeatureDisabledError
            raise FeatureDisabledError(
                Feature.INPROCESS,
                "Install with: pip install 'agentic-concierge[nano]'",
            )
        self.model_path = model_path
        self.n_ctx = n_ctx
        self._engine: Any = None

    def _get_engine(self) -> Any:
        """Lazy-load and cache the mistral.rs engine."""
        if self._engine is None:
            import mistralrs  # type: ignore[import]
            self._engine = mistralrs.Runner(
                which=mistralrs.Which.Gguf(
                    tok_model_id=None,
                    quantized_filename=self.model_path,
                ),
                in_situ_quant=None,
            )
        return self._engine

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
        """Run in-process chat completion via mistral.rs (async wrapper)."""
        import asyncio
        return await asyncio.to_thread(
            self._chat_sync, messages, model, tools, temperature, top_p, max_tokens
        )

    def _chat_sync(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        tools: Optional[List[Dict[str, Any]]],
        temperature: float,
        top_p: float,
        max_tokens: int,
    ) -> LLMResponse:
        """Synchronous inference — runs in a thread pool via ``asyncio.to_thread``."""
        import json as jsonlib
        import mistralrs  # type: ignore[import]

        engine = self._get_engine()
        request = mistralrs.ChatCompletionRequest(
            model=model,
            messages=messages,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            tools=tools or [],
        )
        response = engine.send_chat_completion_request(request)
        choice = response.choices[0]
        msg = choice.message

        tool_calls: List[ToolCallRequest] = []
        for i, tc in enumerate(getattr(msg, "tool_calls", None) or []):
            call_id = getattr(tc, "id", None) or f"call_{i}"
            fn = tc.function
            raw_args = fn.arguments
            if isinstance(raw_args, str):
                try:
                    arguments = jsonlib.loads(raw_args)
                except jsonlib.JSONDecodeError:
                    arguments = {"_raw": raw_args}
            else:
                arguments = raw_args or {}
            tool_calls.append(
                ToolCallRequest(call_id=call_id, tool_name=fn.name, arguments=arguments)
            )

        return LLMResponse(content=getattr(msg, "content", None) or "", tool_calls=tool_calls)
