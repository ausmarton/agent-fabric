"""Base specialist pack: system prompt, OpenAI tool definitions, execute_tool."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Tuple


class BaseSpecialistPack:
    """Concrete ``SpecialistPack``: holds system prompt, tool definitions, and executors.

    ``tools`` maps tool name → ``(openai_tool_def, executor_fn)``.  The finish tool
    definition is stored separately so the loop can detect termination without the
    pack needing to know about the loop.  The finish tool is **included** in
    ``tool_definitions`` (so the LLM knows about it) but is **not** in the executor
    map (the loop handles it directly by extracting the arguments as the final
    payload).
    """

    FINISH_TOOL_NAME = "finish_task"

    def __init__(
        self,
        specialist_id: str,
        system_prompt: str,
        tools: Dict[str, Tuple[Dict[str, Any], Callable[..., Dict[str, Any]]]],
        finish_tool_def: Dict[str, Any],
    ):
        """
        Args:
            specialist_id: Identifier (e.g. ``"engineering"``).
            system_prompt: System message for this specialist.
            tools: Regular (non-finish) tools: ``name → (openai_def, executor)``.
                ``openai_def`` is a full OpenAI function tool definition dict.
            finish_tool_def: OpenAI tool definition for ``finish_task`` (the
                terminal tool).  Its arguments become the run payload.
        """
        self._specialist_id = specialist_id
        self._system_prompt = system_prompt
        self._tools: Dict[str, Tuple[Dict[str, Any], Callable[..., Dict[str, Any]]]] = dict(tools)
        self._finish_tool_def = finish_tool_def

    @property
    def specialist_id(self) -> str:
        return self._specialist_id

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    @property
    def tool_definitions(self) -> List[Dict[str, Any]]:
        """All tool definitions (regular + finish) in OpenAI format."""
        return [defn for defn, _ in self._tools.values()] + [self._finish_tool_def]

    @property
    def tool_names(self) -> List[str]:
        """Names of regular tools (excludes finish tool)."""
        return list(self._tools.keys())

    @property
    def finish_tool_name(self) -> str:
        return self.FINISH_TOOL_NAME

    @property
    def finish_required_fields(self) -> List[str]:
        """Required argument field names derived from the finish tool's parameter schema."""
        return list(
            self._finish_tool_def.get("function", {})
            .get("parameters", {})
            .get("required", [])
        )

    def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a regular (non-finish) tool by name.

        Raises:
            KeyError: When ``tool_name`` is not a known regular tool.
        """
        if tool_name not in self._tools:
            return {"error": f"Unknown tool: {tool_name!r}. Available: {list(self._tools)}"}
        _, fn = self._tools[tool_name]
        return fn(**args)
