"""Pytest fixtures and helpers for agent-fabric tests."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

# Repo root (parent of tests/)
REPO_ROOT = Path(__file__).resolve().parent.parent


def real_llm_reachable():
    """
    Return (config, model_cfg) if the configured default LLM is reachable, else None.
    Used to skip real-LLM tests when no server is available (e.g. CI without Ollama).
    """
    from agent_fabric.config import load_config
    from agent_fabric.infrastructure.llm_bootstrap import _check_reachable

    cfg = load_config()
    model_cfg = cfg.models.get("quality") or cfg.models.get("fast")
    if not model_cfg:
        return None
    try:
        if not _check_reachable(model_cfg.base_url, timeout_s=3.0):
            return None
    except Exception:
        return None
    return (cfg, model_cfg)


def skip_if_no_real_llm():
    """Call pytest.skip if real LLM is not reachable."""
    if real_llm_reachable() is None:
        pytest.skip("Real LLM not reachable (start Ollama and pull a model to run this test)")


# Optional: env to force skipping real-LLM tests even when server is up (e.g. slow CI)
SKIP_REAL_LLM = os.environ.get("FABRIC_SKIP_REAL_LLM", "").lower() in ("1", "true", "yes")
