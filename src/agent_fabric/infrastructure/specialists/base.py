"""Base specialist pack: system prompt, tool list, execute_tool."""

from __future__ import annotations

from typing import Any, Callable, Dict, List


class BaseSpecialistPack:
    """Concrete SpecialistPack: system_prompt, tool_names, tool_loop_prompt, execute_tool."""

    def __init__(
        self,
        specialist_id: str,
        system_prompt: str,
        tool_loop_prompt_template: str,
        tools: Dict[str, tuple[Dict[str, Any], Callable[..., Dict[str, Any]]]],
    ):
        self._specialist_id = specialist_id
        self._system_prompt = system_prompt
        self._tool_loop_prompt_template = tool_loop_prompt_template
        self._tools = dict(tools)

    @property
    def specialist_id(self) -> str:
        return self._specialist_id

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    @property
    def tool_names(self) -> List[str]:
        return list(self._tools.keys())

    def tool_loop_prompt(self, tool_names_str: str) -> str:
        return self._tool_loop_prompt_template.format(tool_names=tool_names_str)

    def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name not in self._tools:
            return {"error": f"Unknown tool: {tool_name}"}
        _, fn = self._tools[tool_name]
        return fn(**args)
