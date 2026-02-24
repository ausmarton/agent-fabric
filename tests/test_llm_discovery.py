"""Tests for LLM discovery and model selection (chat vs embedding)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agent_fabric.infrastructure.llm_discovery import (
    _is_ollama_chat_capable,
    _ollama_model_name,
    discover_ollama_models,
    resolve_llm,
    select_model,
)
from agent_fabric.config.schema import DEFAULT_CONFIG


@pytest.mark.parametrize("model,expected", [
    ({"name": "bge-m3:latest", "model": "bge-m3:latest", "details": {"family": "bge-m3"}}, False),
    ({"name": "nomic-embed-text", "details": {"family": "nomic-embed-text"}}, False),
    ({"name": "qwen2.5:7b", "details": {"family": "qwen2.5"}}, True),
    ({"name": "llama3.1:8b", "details": {"family": "llama"}}, True),
])
def test_is_ollama_chat_capable(model, expected):
    assert _is_ollama_chat_capable(model) is expected


def test_select_model_prefers_chat_models():
    """When both chat and embedding models exist, selection uses only chat-capable list."""
    all_models = [
        {"name": "bge-m3:latest", "model": "bge-m3:latest", "details": {"family": "bge-m3"}},
        {"name": "qwen2.5:7b", "model": "qwen2.5:7b", "details": {"family": "qwen2.5", "parameter_size": "7B"}},
    ]
    chat_only = [m for m in all_models if _is_ollama_chat_capable(m)]
    names = [_ollama_model_name(m) for m in chat_only]
    assert "bge-m3:latest" not in names
    assert "qwen2.5:7b" in names
    # 14b not in list → fallback to 7b
    selected = select_model("qwen2.5:14b", chat_only, is_ollama=True)
    assert selected == "qwen2.5:7b"


def test_resolve_llm_filters_embedding_models():
    """resolve_llm with mocked discover returns a chat model even when an embedding model is first."""
    models = [
        {"name": "bge-m3:latest", "model": "bge-m3:latest", "details": {"family": "bge-m3"}},
        {"name": "qwen2.5:7b", "model": "qwen2.5:7b", "details": {"family": "qwen2.5", "parameter_size": "7B"}},
    ]
    with patch("agent_fabric.infrastructure.llm_discovery.discover_ollama_models", return_value=models):
        with patch("agent_fabric.infrastructure.llm_bootstrap.ensure_llm_available", return_value=True):
            resolved = resolve_llm(DEFAULT_CONFIG, "quality")
    assert resolved.model != "bge-m3:latest"
    assert resolved.model == "qwen2.5:7b"
