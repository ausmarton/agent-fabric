"""Domain models: RunId, Task, RunResult, ToolCallRequest, LLMResponse. Pure data, no I/O."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class RunId:
    """Unique identifier for a single run (e.g. timestamp + random suffix)."""
    value: str


@dataclass
class Task:
    """User task: prompt and optional constraints."""
    prompt: str
    specialist_id: Optional[str] = None  # If set, use this specialist; else recruit
    model_key: str = "quality"
    network_allowed: bool = True


def build_task(
    prompt: str,
    pack: Optional[str],
    model_key: str,
    network_allowed: bool,
) -> "Task":
    """Construct a Task from external input, normalising the pack string.

    ``pack`` may be ``None``, an empty string, or whitespace-only — all are
    treated as "no specialist requested" (auto-routing).  A non-empty value
    is stripped of surrounding whitespace before being stored as
    ``specialist_id``.

    Both the CLI (where Typer supplies ``""`` as default) and the HTTP API
    (where the field is ``Optional[str]``) use this helper so the
    normalisation logic lives in exactly one place.
    """
    return Task(
        prompt=prompt,
        specialist_id=(pack or "").strip() or None,
        model_key=model_key,
        network_allowed=network_allowed,
    )


@dataclass
class ToolCallRequest:
    """A single tool call requested by the LLM in a response."""
    call_id: str        # Opaque ID, used to correlate with tool results in the message history
    tool_name: str
    arguments: Dict[str, Any]


@dataclass
class LLMResponse:
    """Response from the LLM after a chat turn.

    Either the LLM returns tool calls (``tool_calls`` non-empty, ``content`` typically
    None/empty) or it returns a plain text response (``content`` set, ``tool_calls``
    empty).  The execute-task loop uses ``has_tool_calls`` to decide the next step.
    """
    content: Optional[str]
    tool_calls: List[ToolCallRequest] = field(default_factory=list)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


@dataclass
class RunResult:
    """Result of executing a task: run id, paths, and final payload."""
    run_id: RunId
    run_dir: str
    workspace_path: str
    specialist_id: str
    model_name: str
    payload: Dict[str, Any]
    required_capabilities: List[str] = field(default_factory=list)
