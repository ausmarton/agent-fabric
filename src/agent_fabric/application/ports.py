"""Ports (abstract interfaces) used by the application layer."""

from __future__ import annotations

from typing import Any, Dict, List, Protocol

from agent_fabric.config import ModelConfig
from agent_fabric.domain import RunId, RunResult


class ChatClient(Protocol):
    """LLM chat interface (OpenAI chat-completions API). Implemented by OllamaChatClient by default; any backend exposing POST /v1/chat/completions works."""
    async def chat(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        temperature: float = 0.1,
        top_p: float = 0.9,
        max_tokens: int = 2048,
    ) -> str: ...


class RunRepository(Protocol):
    """Create runs and append run-log events."""
    def create_run(self) -> tuple[RunId, str, str]:
        """Create a new run directory; return (RunId, run_dir path, workspace path)."""
        ...

    def append_event(self, run_id: RunId, kind: str, payload: Dict[str, Any], step: str | None = None) -> None: ...


class SpecialistPack(Protocol):
    """A specialist pack: system prompt, tool names, and tool execution."""
    @property
    def specialist_id(self) -> str: ...

    @property
    def system_prompt(self) -> str: ...

    @property
    def tool_names(self) -> List[str]: ...

    def tool_loop_prompt(self, tool_names_str: str) -> str: ...

    def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]: ...


class SpecialistRegistry(Protocol):
    """Resolve a specialist pack by id."""
    def get_pack(
        self,
        specialist_id: str,
        workspace_path: str,
        network_allowed: bool,
    ) -> SpecialistPack: ...

    def list_ids(self) -> List[str]: ...
