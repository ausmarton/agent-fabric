"""Tests for LLM bootstrap: ensure_llm_available and reachability check."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from agentic_concierge.infrastructure.llm_bootstrap import (
    _check_reachable,
    _health_url,
    ensure_llm_available,
)


def test_health_url_v1_base():
    assert _health_url("http://localhost:11434/v1") == "http://localhost:11434/"
    assert _health_url("https://host:9999/v1") == "https://host:9999/"


def test_health_url_other():
    assert _health_url("http://localhost:8000") == "http://localhost:8000"
    assert _health_url("http://localhost:8000/") == "http://localhost:8000"


def test_check_reachable_unreachable():
    # Non-routing or closed port
    assert _check_reachable("http://127.0.0.1:31999/", timeout_s=0.5) is False


def test_ensure_llm_available_unreachable_no_cmd():
    assert ensure_llm_available("http://127.0.0.1:31999/", start_cmd=None) is False


def test_ensure_llm_available_invalid_cmd_raises():
    with pytest.raises(FileNotFoundError) as exc_info:
        ensure_llm_available(
            "http://127.0.0.1:31999/",
            start_cmd=["/nonexistent/ollama", "serve"],
            timeout_s=2,
        )
    assert "Cannot start LLM server" in str(exc_info.value)


def test_ensure_llm_available_timeout_raises():
    # Start a command that exits immediately and doesn't listen, so URL never becomes ready
    with pytest.raises(TimeoutError) as exc_info:
        ensure_llm_available(
            "http://127.0.0.1:31999/",
            start_cmd=["true"],
            timeout_s=1,
            poll_interval_s=0.3,
        )
    assert "did not become ready" in str(exc_info.value)


def test_ensure_llm_available_starts_then_reachable():
    """When unreachable then start_cmd runs, ensure_llm_available returns True once server is reachable (mocked)."""
    with patch("agentic_concierge.infrastructure.llm_bootstrap._check_reachable", side_effect=[False, True]):
        with patch("agentic_concierge.infrastructure.llm_bootstrap.subprocess.Popen", return_value=MagicMock()):
            result = ensure_llm_available(
                "http://127.0.0.1:31999/",
                start_cmd=["ollama", "serve"],
                timeout_s=5,
                poll_interval_s=0.01,
            )
    assert result is True
