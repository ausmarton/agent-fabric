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


def test_ollama_embedding_model_excluded():
    """Embedding-only models (e.g. bge-m3) are excluded from chat selection."""
    assert _is_ollama_chat_capable({"name": "bge-m3:latest", "model": "bge-m3:latest", "details": {"family": "bge-m3"}}) is False
    assert _is_ollama_chat_capable({"name": "nomic-embed-text", "details": {"family": "nomic-embed-text"}}) is False
    assert _is_ollama_chat_capable({"name": "qwen2.5:7b", "details": {"family": "qwen2.5"}}) is True
    assert _is_ollama_chat_capable({"name": "llama3.1:8b", "details": {"family": "llama"}}) is True


def test_select_model_prefers_chat_models():
    """When both chat and embedding models exist, selection uses only chat-capable list."""
    # Simulate /api/tags with one embedding and one chat model
    all_models = [
        {"name": "bge-m3:latest", "model": "bge-m3:latest", "details": {"family": "bge-m3"}},
        {"name": "qwen2.5:7b", "model": "qwen2.5:7b", "details": {"family": "qwen2.5", "parameter_size": "7B"}},
    ]
    chat_only = [m for m in all_models if _is_ollama_chat_capable(m)]
    names = [_ollama_model_name(m) for m in chat_only]
    assert "bge-m3:latest" not in names
    assert "qwen2.5:7b" in names
    selected = select_model("qwen2.5:14b", chat_only, is_ollama=True)  # 14b not in list, so fallback to 7b
    assert selected == "qwen2.5:7b"


@pytest.mark.skip(reason="requires reachable Ollama or more mocking")
def test_resolve_llm_filters_embedding_models():
    """resolve_llm with mocked discover returns a chat model when only bge-m3 would otherwise be first."""
    with patch("agent_fabric.infrastructure.llm_discovery.discover_ollama_models") as discover:
        discover.return_value = [
            {"name": "bge-m3:latest", "model": "bge-m3:latest", "details": {"family": "bge-m3"}},
            {"name": "qwen2.5:7b", "model": "qwen2.5:7b", "details": {"family": "qwen2.5", "parameter_size": "7B"}},
        ]
        with patch("agent_fabric.infrastructure.llm_discovery.ensure_llm_available"):
            resolved = resolve_llm(DEFAULT_CONFIG, "quality")
            assert resolved.model != "bge-m3:latest"
            assert resolved.model == "qwen2.5:7b"
