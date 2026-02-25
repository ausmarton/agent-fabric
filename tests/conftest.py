"""Pytest fixtures and helpers for agentic-concierge tests."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

# Repo root (parent of tests/)
REPO_ROOT = Path(__file__).resolve().parent.parent


def real_llm_reachable():
    """Return ``(cfg, resolved_model_cfg)`` if a live LLM is reachable, else ``None``.

    Uses ``resolve_llm`` so the returned model config points at the *actual*
    available model on the server (which may differ from the configured default
    if that model hasn't been pulled).
    """
    from agentic_concierge.config import load_config
    from agentic_concierge.infrastructure.llm_bootstrap import _check_reachable
    from agentic_concierge.infrastructure.llm_discovery import resolve_llm

    cfg = load_config()
    model_cfg = cfg.models.get("quality") or cfg.models.get("fast")
    if not model_cfg:
        return None
    try:
        if not _check_reachable(model_cfg.base_url, timeout_s=3.0):
            return None
    except Exception:
        return None

    # Resolve the actual available model so tests don't get a 404 for the
    # configured but not-yet-pulled default.
    try:
        resolved = resolve_llm(cfg, "quality")
        return cfg, resolved.model_config
    except Exception:
        return None


def skip_if_no_real_llm():
    """Call pytest.skip if real LLM is not reachable."""
    if real_llm_reachable() is None:
        pytest.skip("Real LLM not reachable (start Ollama and pull a model to run this test)")


# Optional: env to force skipping real-LLM tests even when server is up (e.g. slow CI)
SKIP_REAL_LLM = os.environ.get("CONCIERGE_SKIP_REAL_LLM", "").lower() in ("1", "true", "yes")


@pytest.fixture(autouse=True)
def _reset_config_cache():
    """Clear the load_config LRU cache and reset _env before (and after) every test.

    This ensures each test gets a fresh config load, so monkeypatching
    CONCIERGE_CONFIG_PATH or _env works correctly without tests bleeding into each other.
    Existing tests that call ``monkeypatch.setattr(config_loader, "_env", None)``
    continue to work unchanged (those resets are now redundant but harmless).
    """
    from agentic_concierge.config import loader as config_loader
    config_loader.load_config.cache_clear()
    config_loader._env = None
    yield
    config_loader.load_config.cache_clear()
    config_loader._env = None
