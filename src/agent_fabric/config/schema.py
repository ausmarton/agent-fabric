"""Configuration schema. Defaults point at Ollama; any OpenAI-compatible backend works via base_url + model."""

from __future__ import annotations

from typing import Dict, List

from pydantic import BaseModel, Field


class ModelConfig(BaseModel):
    """LLM endpoint and model name (OpenAI chat-completions API). Defaults: Ollama."""
    base_url: str = Field(..., description="e.g. http://localhost:11434/v1 or http://localhost:8000/v1")
    model: str = Field(..., description="Model name (e.g. qwen2.5:7b for Ollama, or your server's model id)")
    api_key: str = Field("", description="Bearer token; empty for local backends (no header sent), set for cloud.")
    temperature: float = 0.1
    top_p: float = 0.9
    max_tokens: int = 2048
    timeout_s: float = Field(default=360.0, description="HTTP timeout for chat request (read). Large models may need 300–600s.")


class SpecialistConfig(BaseModel):
    """Specialist pack definition in config."""
    description: str
    keywords: List[str] = Field(default_factory=list)
    workflow: str  # Reserved for future; today we use specialist_id to load pack


class FabricConfig(BaseModel):
    """Root config: models and specialists."""
    models: Dict[str, ModelConfig]
    specialists: Dict[str, SpecialistConfig]
    require_human_approval_for: List[str] = Field(
        default_factory=lambda: ["deploy", "push", "write_external"]
    )
    # Local LLM is default and primary: ensure it's available (start if needed) by default.
    local_llm_ensure_available: bool = Field(
        True,
        description="If True (default), ensure local LLM is reachable; start it via local_llm_start_cmd when unreachable. Set False if you manage the server yourself.",
    )
    local_llm_start_cmd: List[str] = Field(
        default_factory=lambda: ["ollama", "serve"],
        description="Command to start the local LLM server when unreachable (e.g. ollama serve).",
    )
    local_llm_start_timeout_s: int = Field(
        90,
        description="Seconds to wait for local LLM server to become ready after start.",
    )
    auto_pull_if_missing: bool = Field(
        True,
        description="If True (default), when no models are available at the configured backend (e.g. Ollama), pull auto_pull_model so one command works.",
    )
    auto_pull_model: str = Field(
        "qwen2.5:7b",
        description="Model to pull when auto_pull_if_missing is True and no models are available.",
    )


# Default: Ollama on localhost:11434
DEFAULT_CONFIG = FabricConfig(
    models={
        "fast": ModelConfig(
            base_url="http://localhost:11434/v1",
            model="qwen2.5:7b",
            temperature=0.1,
            max_tokens=1200,
        ),
        "quality": ModelConfig(
            base_url="http://localhost:11434/v1",
            model="qwen2.5:14b",
            temperature=0.1,
            max_tokens=2400,
        ),
    },
    specialists={
        "engineering": SpecialistConfig(
            description="Plan → implement → test → review → iterate.",
            keywords=["build", "implement", "code", "service", "pipeline", "kubernetes", "gcp", "scala", "rust", "python"],
            workflow="engineering",
        ),
        "research": SpecialistConfig(
            description="Scope → search → screen → extract → synthesize.",
            keywords=["literature", "systematic review", "paper", "arxiv", "survey", "bibliography", "citations"],
            workflow="research",
        ),
    },
)
