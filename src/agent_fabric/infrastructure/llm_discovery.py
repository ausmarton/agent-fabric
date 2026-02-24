"""
Discover available LLM backends and models, select the best match, and optionally
auto-pull a default model so one command works without manual setup.

Strategy (from LLM_OPTIONS.md / BACKENDS.md): prefer what's available on the host—
Ollama (default), vLLM, etc.—and pick a model that matches config or the best available.
"""

from __future__ import annotations

import logging
import re
import subprocess
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from agent_fabric.config import FabricConfig, ModelConfig
from agent_fabric.config.constants import LLM_DISCOVERY_TIMEOUT_S, LLM_PULL_TIMEOUT_S

logger = logging.getLogger(__name__)


@dataclass
class ResolvedLLM:
    """Result of resolving which backend and model to use."""
    base_url: str
    model: str
    model_config: ModelConfig  # full config (temperature, etc.) to use for chat


def _ollama_root(base_url: str) -> str:
    """Ollama API root: strip /v1 from base_url (e.g. http://localhost:11434/v1 -> http://localhost:11434)."""
    u = urlparse(base_url)
    path = u.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[:-3] or "/"
    return f"{u.scheme}://{u.netloc}{path}".rstrip("/") or base_url


def discover_ollama_models(base_url: str, timeout_s: float = LLM_DISCOVERY_TIMEOUT_S) -> list[dict] | None:
    """
    Query Ollama for available models (GET /api/tags). Returns list of model dicts
    (name, details.parameter_size, etc.) or None if not Ollama / unreachable.
    """
    root = _ollama_root(base_url)
    try:
        with httpx.Client(timeout=timeout_s) as client:
            r = client.get(f"{root}/api/tags")
            if r.status_code != 200:
                return None
            data = r.json()
            return data.get("models") or []
    except Exception:
        return None


def discover_openai_models(base_url: str, timeout_s: float = LLM_DISCOVERY_TIMEOUT_S) -> list[str] | None:
    """
    Query an OpenAI-compatible /v1/models endpoint (e.g. vLLM). Returns list of model ids or None.
    """
    url = f"{base_url.rstrip('/')}/models"
    try:
        with httpx.Client(timeout=timeout_s) as client:
            r = client.get(url)
            if r.status_code != 200:
                return None
            data = r.json()
            # OpenAI format: { "data": [ { "id": "..." }, ... ] }
            items = data.get("data") or []
            return [m.get("id") for m in items if m.get("id")]
    except Exception:
        return None


def _ollama_model_name(m: dict) -> str:
    """Preferred name for an Ollama model entry."""
    return m.get("name") or m.get("model") or ""


# Embedding-only models (Ollama returns them in /api/tags but they "do not support chat")
_EMBEDDING_ONLY_FAMILIES_OR_NAMES = frozenset(
    s.lower()
    for s in (
        "bge",
        "bge-m3",
        "nomic-embed",
        "mxbai-embed",
        "snowflake-arctic-embed",
        "all-minilm",
        "nomic-embed-text",
        "multilingual-e5",
    )
)


def _is_ollama_chat_capable(m: dict) -> bool:
    """True if this Ollama model is suitable for chat/completion (exclude embedding-only)."""
    name = (_ollama_model_name(m) or "").lower()
    details = m.get("details") or {}
    family = (details.get("family") or "").lower()
    families = [f.lower() for f in details.get("families") or []]
    for prefix in _EMBEDDING_ONLY_FAMILIES_OR_NAMES:
        if name.startswith(prefix) or family.startswith(prefix) or any(f.startswith(prefix) for f in families):
            return False
    if "embed" in name and "chat" not in name and "instruct" not in name:
        return False
    return True


def _param_size_sort_key(name: str, details: dict | None) -> tuple:
    """Sort key: param size as float billions (smaller = faster / preferred fallback).

    Parses Ollama ``parameter_size`` strings such as ``"8.0B"``, ``"15B"``,
    ``"33.4B"``, ``"334M"`` into comparable floats.  Unknown size sorts last.
    """
    param = (details or {}).get("parameter_size") or ""
    m = re.match(r"([\d.]+)\s*([BbMmKk])", param.strip())
    if not m:
        return (999.0, name)  # unknown → deprioritise
    val = float(m.group(1))
    unit = m.group(2).upper()
    if unit == "K":
        val /= 1_000_000.0
    elif unit == "M":
        val /= 1_000.0
    # "B" → already in billions
    return (val, name)


def select_model(
    preferred_model: str,
    available: list[dict] | list[str],
    *,
    is_ollama: bool = True,
) -> str | None:
    """
    Select best model from available list. If preferred_model is in the list, use it.
    Otherwise pick the smallest available (by parameter size) so we avoid timeouts on huge models.
    Returns None if available is empty.
    """
    if not available:
        return None
    if is_ollama:
        names = [m for m in (_ollama_model_name(m) for m in available) if m]
        if preferred_model in names:
            return preferred_model
        # Fallback: prefer smallest param size (faster, less likely to timeout)
        name_to_entry = {_ollama_model_name(m): m for m in available}
        details_by_name = {n: (name_to_entry.get(n) or {}).get("details") for n in names}
        sorted_names = sorted(names, key=lambda n: _param_size_sort_key(n, details_by_name.get(n)))
        return sorted_names[0] if sorted_names else None
    else:
        # OpenAI/vLLM: list of id strings
        ids = [s for s in available if isinstance(s, str) and s]
        if preferred_model in ids:
            return preferred_model
        return ids[0] if ids else None


def _ollama_pull(model: str, ollama_root: str, timeout_s: int = 600) -> bool:
    """Run ollama pull <model>. Assumes ollama CLI is on PATH. Returns True if pull succeeded."""
    try:
        subprocess.run(
            ["ollama", "pull", model],
            capture_output=True,
            timeout=timeout_s,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


def resolve_llm(
    config: FabricConfig,
    model_key: str,
    *,
    ensure_available: bool | None = None,
    start_cmd: list[str] | None = None,
    timeout_s: int | None = None,
) -> ResolvedLLM:
    """
    Determine which backend and model to use so that one command works.

    1. Use model profile from config (e.g. quality -> base_url, model).
    2. Ensure server is reachable (start via local_llm_start_cmd if configured).
    3. Discover models (Ollama /api/tags or OpenAI /models).
    4. If configured model is available, use it.
    5. If no models and auto_pull_if_missing: pull auto_pull_model, then rediscover.
    6. Select best available model (preferred or fallback by size/order).
    7. Return ResolvedLLM(base_url, model, model_config).

    Raises RuntimeError if no backend or no model can be used (e.g. server down, pull failed).
    """
    from agent_fabric.infrastructure.llm_bootstrap import ensure_llm_available

    model_cfg = config.models.get(model_key) or config.models["quality"]
    ensure_available = config.local_llm_ensure_available if ensure_available is None else ensure_available
    start_cmd = config.local_llm_start_cmd if start_cmd is None else start_cmd
    timeout_s = config.local_llm_start_timeout_s if timeout_s is None else timeout_s

    if ensure_available and start_cmd:
        try:
            ensure_llm_available(
                model_cfg.base_url,
                start_cmd=start_cmd,
                timeout_s=timeout_s,
            )
        except (TimeoutError, FileNotFoundError) as e:
            raise RuntimeError(
                f"Could not start or reach local LLM at {model_cfg.base_url}: {e}. "
                "Install Ollama (https://ollama.com) or set local_llm_ensure_available: false."
            ) from e

    # Discover: try Ollama first (default base_url is Ollama)
    ollama_root = _ollama_root(model_cfg.base_url)
    models = discover_ollama_models(model_cfg.base_url, timeout_s=15.0)
    if models is not None:
        # Exclude embedding-only models (they appear in /api/tags but "do not support chat")
        models = [m for m in models if _is_ollama_chat_capable(m)]
        # Ollama: we have a list of dicts
        names = [m for m in (_ollama_model_name(m) for m in models) if m]
        selected = select_model(model_cfg.model, models, is_ollama=True)
        if selected:
            if selected != model_cfg.model:
                logger.warning(
                    "Preferred model %r not available; using fallback: %s (available: %s)",
                    model_cfg.model, selected, names[:5],
                )
            else:
                logger.info("Resolved model: %s at %s", selected, model_cfg.base_url)
            resolved_config = ModelConfig(
                base_url=model_cfg.base_url,
                model=selected,
                api_key=model_cfg.api_key,
                temperature=model_cfg.temperature,
                top_p=model_cfg.top_p,
                max_tokens=model_cfg.max_tokens,
                timeout_s=model_cfg.timeout_s,
            )
            return ResolvedLLM(base_url=model_cfg.base_url, model=selected, model_config=resolved_config)
        # No models: optional auto-pull
        if config.auto_pull_if_missing:
            pull_model = config.auto_pull_model
            logger.info("No models at %s; auto-pulling %s", model_cfg.base_url, pull_model)
            if _ollama_pull(pull_model, ollama_root, timeout_s=LLM_PULL_TIMEOUT_S):
                time.sleep(1.0)  # allow Ollama to register the new model
                models2 = discover_ollama_models(model_cfg.base_url, timeout_s=15.0)
                if models2:
                    models2 = [m for m in models2 if _is_ollama_chat_capable(m)]
                if models2:
                    selected = select_model(pull_model, models2, is_ollama=True) or _ollama_model_name(models2[0])
                    resolved_config = ModelConfig(
                        base_url=model_cfg.base_url,
                        model=selected,
                        api_key=model_cfg.api_key,
                        temperature=model_cfg.temperature,
                        top_p=model_cfg.top_p,
                        max_tokens=model_cfg.max_tokens,
                        timeout_s=model_cfg.timeout_s,
                    )
                    return ResolvedLLM(base_url=model_cfg.base_url, model=selected, model_config=resolved_config)
        raise RuntimeError(
            f"No models available at {model_cfg.base_url}. Pull one with: ollama pull {config.auto_pull_model}"
        )

    # Not Ollama or unreachable: try OpenAI-compat (e.g. vLLM) at same base_url
    logger.info("Ollama not reachable at %s; trying OpenAI-compat endpoint", model_cfg.base_url)
    openai_models = discover_openai_models(model_cfg.base_url, timeout_s=LLM_DISCOVERY_TIMEOUT_S)
    if openai_models:
        selected = select_model(model_cfg.model, openai_models, is_ollama=False)
        if selected:
            logger.info("Resolved model (OpenAI-compat): %s at %s", selected, model_cfg.base_url)
            resolved_config = ModelConfig(
                base_url=model_cfg.base_url,
                model=selected,
                api_key=model_cfg.api_key,
                temperature=model_cfg.temperature,
                top_p=model_cfg.top_p,
                max_tokens=model_cfg.max_tokens,
                timeout_s=model_cfg.timeout_s,
            )
            return ResolvedLLM(base_url=model_cfg.base_url, model=selected, model_config=resolved_config)

    raise RuntimeError(
        f"Could not discover any models at {model_cfg.base_url}. "
        "For Ollama: ensure it is running and run 'ollama pull <model>'. "
        "Set FABRIC_CONFIG_PATH to point at a backend that has models."
    )
