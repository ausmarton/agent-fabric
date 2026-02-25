"""Configuration: schema, loading from env/file, and shared constants."""

from .schema import DEFAULT_CONFIG, ConciergeConfig, ModelConfig, SpecialistConfig
from .loader import load_config
from .constants import (
    MAX_TOOL_OUTPUT_CHARS,
    MAX_LLM_CONTENT_IN_RUNLOG_CHARS,
    LLM_DISCOVERY_TIMEOUT_S,
    LLM_CHAT_DEFAULT_TIMEOUT_S,
    SHELL_DEFAULT_TIMEOUT_S,
    LLM_PULL_TIMEOUT_S,
)

get_config = load_config  # alias

__all__ = [
    "DEFAULT_CONFIG", "ConciergeConfig", "ModelConfig", "SpecialistConfig",
    "load_config", "get_config",
    "MAX_TOOL_OUTPUT_CHARS", "MAX_LLM_CONTENT_IN_RUNLOG_CHARS",
    "LLM_DISCOVERY_TIMEOUT_S", "LLM_CHAT_DEFAULT_TIMEOUT_S",
    "SHELL_DEFAULT_TIMEOUT_S", "LLM_PULL_TIMEOUT_S",
]
