"""LLM client factory: build the right ChatClient for a ModelConfig."""

from __future__ import annotations

from agent_fabric.config.schema import ModelConfig
from agent_fabric.application.ports import ChatClient


def build_chat_client(model_config: ModelConfig) -> ChatClient:
    """Return the correct ``ChatClient`` implementation for *model_config*.

    Dispatch is based on ``model_config.backend``:

    ``"ollama"`` (default)
        :class:`~agent_fabric.infrastructure.ollama.client.OllamaChatClient` —
        includes the Ollama 400 retry and "does not support tools" error
        detection.

    ``"generic"``
        :class:`~agent_fabric.infrastructure.chat.generic.GenericChatClient` —
        bare OpenAI-compatible client; suitable for cloud providers (OpenAI,
        Anthropic via LiteLLM bridge, vLLM, LM Studio, etc.).

    Raises:
        ValueError: For unknown backend values.
    """
    backend = model_config.backend
    if backend == "ollama":
        from agent_fabric.infrastructure.ollama.client import OllamaChatClient
        return OllamaChatClient(
            base_url=model_config.base_url,
            api_key=model_config.api_key,
            timeout_s=model_config.timeout_s,
        )
    if backend == "generic":
        from agent_fabric.infrastructure.chat.generic import GenericChatClient
        return GenericChatClient(
            base_url=model_config.base_url,
            api_key=model_config.api_key,
            timeout_s=model_config.timeout_s,
        )
    raise ValueError(
        f"Unknown LLM backend {backend!r}. "
        "Supported backends: 'ollama' (default), 'generic' (OpenAI-compatible cloud/vLLM)."
    )
