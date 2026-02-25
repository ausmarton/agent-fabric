"""Load config from CONCIERGE_CONFIG_PATH or return default.

``load_config()`` is memoised with ``functools.lru_cache`` so the file is read
and parsed at most once per process.  Call ``load_config.cache_clear()`` to
force a re-read (useful in tests and when ``CONCIERGE_CONFIG_PATH`` changes at
runtime).
"""

from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

from .schema import ConciergeConfig, DEFAULT_CONFIG


class _Env(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CONCIERGE_", extra="ignore")
    config_path: Optional[str] = None


_env: Optional[_Env] = None


def _get_env() -> _Env:
    global _env
    if _env is None:
        _env = _Env()
    return _env


@functools.lru_cache(maxsize=1)
def load_config() -> ConciergeConfig:
    """Load config from CONCIERGE_CONFIG_PATH if set and valid; else return DEFAULT_CONFIG.

    Result is cached for the lifetime of the process.  Call
    ``load_config.cache_clear()`` to force a reload.
    """
    path = _get_env().config_path
    if not path or not path.strip():
        return DEFAULT_CONFIG
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        return DEFAULT_CONFIG
    raw = p.read_text(encoding="utf-8")
    data = json.loads(raw)
    # Support legacy "packs" key
    if "packs" in data and "specialists" not in data:
        data["specialists"] = data.pop("packs")
    # Backward compat: old config used auto_start_llm, llm_start_cmd, llm_start_timeout_s
    if "auto_start_llm" in data and "local_llm_ensure_available" not in data:
        data["local_llm_ensure_available"] = data.pop("auto_start_llm")
    if "llm_start_cmd" in data and "local_llm_start_cmd" not in data:
        data["local_llm_start_cmd"] = data.pop("llm_start_cmd")
    if "llm_start_timeout_s" in data and "local_llm_start_timeout_s" not in data:
        data["local_llm_start_timeout_s"] = data.pop("llm_start_timeout_s")
    return ConciergeConfig.model_validate(data)
