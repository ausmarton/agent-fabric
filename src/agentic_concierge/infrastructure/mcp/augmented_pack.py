"""MCPAugmentedPack: wraps a SpecialistPack with one or more MCP tool servers."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class MCPAugmentedPack:
    """Decorator that adds MCP server tools to an existing specialist pack.

    On ``aopen()``, all configured MCP sessions are connected and their tool
    definitions are merged with the inner pack's tools.  On ``aclose()``, all
    sessions are disconnected (individual failures are swallowed so a single
    broken server never prevents cleanup).

    ``execute_tool()`` dispatches to the owning MCP session (by prefix) or
    falls through to the inner pack for native tools.

    This class is transparent with respect to the ``SpecialistPack`` protocol:
    it forwards ``specialist_id``, ``system_prompt``, ``finish_tool_name``, and
    ``finish_required_fields`` directly to the inner pack.
    """

    def __init__(self, inner: Any, sessions: List[Any]) -> None:
        """
        Args:
            inner: Any object satisfying the ``SpecialistPack`` protocol.
            sessions: List of ``MCPSessionManager`` instances to attach.
        """
        self._inner = inner
        self._sessions = list(sessions)
        self._mcp_tool_defs: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def aopen(self) -> None:
        """Open inner pack, then connect all MCP sessions and populate MCP tool definitions.

        The inner pack's ``aopen()`` is called first so that base-pack lifecycle
        hooks (e.g. browser tool initialisation) run before the MCP sessions are
        connected.  Raises if any session fails to connect.
        """
        await self._inner.aopen()
        await asyncio.gather(*[s.connect() for s in self._sessions])

        all_tools: List[Dict[str, Any]] = []
        for s in self._sessions:
            all_tools.extend(await s.list_tools())
        self._mcp_tool_defs = all_tools

        logger.debug(
            "MCPAugmentedPack: opened %d session(s), %d MCP tool(s) available",
            len(self._sessions), len(self._mcp_tool_defs),
        )

    async def aclose(self) -> None:
        """Disconnect all MCP sessions then close the inner pack.

        Individual MCP session failures are swallowed so a single broken server
        never prevents cleanup.  The inner pack's ``aclose()`` is always called.
        """
        results = await asyncio.gather(
            *[s.disconnect() for s in self._sessions],
            return_exceptions=True,
        )
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning(
                    "MCPAugmentedPack: session %d failed to disconnect: %s",
                    i, result,
                )
        try:
            await self._inner.aclose()
        except Exception as exc:  # noqa: BLE001
            logger.warning("MCPAugmentedPack: inner pack failed to close: %s", exc)

    # ------------------------------------------------------------------
    # SpecialistPack protocol properties (forwarded to inner pack)
    # ------------------------------------------------------------------

    @property
    def specialist_id(self) -> str:
        return self._inner.specialist_id

    @property
    def system_prompt(self) -> str:
        return self._inner.system_prompt

    @property
    def finish_tool_name(self) -> str:
        return self._inner.finish_tool_name

    @property
    def finish_required_fields(self) -> List[str]:
        return self._inner.finish_required_fields

    @property
    def tool_definitions(self) -> List[Dict[str, Any]]:
        """Inner pack tools plus all MCP server tools (populated after aopen)."""
        return self._inner.tool_definitions + self._mcp_tool_defs

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    async def execute_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatch to owning MCP session, or fall through to the inner pack."""
        for session in self._sessions:
            if session.owns_tool(name):
                return await session.call_tool(name, args)

        # Native tool — delegate to inner pack.
        return await self._inner.execute_tool(name, args)
