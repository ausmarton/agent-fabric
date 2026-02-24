"""Configuration schema. Defaults point at Ollama; any OpenAI-compatible backend works via base_url + model."""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


class ModelConfig(BaseModel):
    """LLM endpoint and model name (OpenAI chat-completions API). Defaults: Ollama."""
    base_url: str = Field(..., description="e.g. http://localhost:11434/v1 or http://localhost:8000/v1")
    model: str = Field(..., description="Model name (e.g. qwen2.5:7b for Ollama, or your server's model id)")
    api_key: str = Field("", description="Bearer token; empty for local backends (no header sent), set for cloud.")
    backend: str = Field(
        "ollama",
        description=(
            "LLM client backend to use. "
            "'ollama' (default): Ollama-compatible client with 400-retry and tool-support detection. "
            "'generic': bare OpenAI-compatible client for cloud providers (OpenAI, Anthropic via "
            "LiteLLM bridge, vLLM, LM Studio, etc.)."
        ),
    )
    temperature: float = 0.1
    top_p: float = 0.9
    max_tokens: int = 2048
    timeout_s: float = Field(default=360.0, description="HTTP timeout for chat request (read). Large models may need 300–600s.")


class SpecialistConfig(BaseModel):
    """Specialist pack definition in config."""
    description: str
    keywords: List[str] = Field(default_factory=list)
    workflow: str  # Reserved for future; today we use specialist_id to load pack
    capabilities: List[str] = Field(
        default_factory=list,
        description=(
            "Capability IDs this pack can provide "
            "(e.g. 'code_execution', 'systematic_review', 'web_search'). "
            "Used by the capability-based router (Phase 2+) to match tasks to packs."
        ),
    )
    builder: Optional[str] = Field(
        None,
        description=(
            "Dotted import path to the pack factory function, "
            "e.g. 'mypackage.packs.custom:build_custom_pack'. "
            "Signature: (workspace_path: str, network_allowed: bool) -> SpecialistPack. "
            "When omitted the built-in pack for this specialist id is used."
        ),
    )


class TelemetryConfig(BaseModel):
    """Optional OpenTelemetry tracing configuration."""
    enabled: bool = False
    service_name: str = "agent-fabric"
    exporter: str = Field(
        "none",
        description="Span exporter: 'none' (default), 'console' (stdout), or 'otlp' (gRPC endpoint).",
    )
    otlp_endpoint: str = Field(
        "",
        description="OTLP gRPC endpoint, e.g. 'http://localhost:4317'. Required when exporter='otlp'.",
    )


class FabricConfig(BaseModel):
    """Root config: models and specialists."""
    models: Dict[str, ModelConfig]
    specialists: Dict[str, SpecialistConfig]
    telemetry: Optional[TelemetryConfig] = None

    @model_validator(mode="after")
    def _specialists_not_empty(self) -> "FabricConfig":
        """Validate that at least one specialist is defined.

        An empty specialists dict means every recruit_specialist() call fails
        at execution time with an opaque KeyError.  Catching this at config
        load time gives a clear, early error message.

        As new fields that reference specialist IDs are added to FabricConfig
        (e.g. a future ``default_specialist`` or routing rules), add those
        cross-reference checks here.
        """
        if not self.specialists:
            raise ValueError(
                "specialists must not be empty: at least one specialist must be defined. "
                "Add an 'engineering' or 'research' entry (or a custom pack) to your config."
            )
        return self
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
            capabilities=["code_execution", "file_io", "software_testing"],
        ),
        "research": SpecialistConfig(
            description="Scope → search → screen → extract → synthesize.",
            keywords=["literature", "systematic review", "paper", "arxiv", "survey", "bibliography", "citations"],
            workflow="research",
            capabilities=["systematic_review", "web_search", "citation_extraction", "file_io"],
        ),
    },
)
