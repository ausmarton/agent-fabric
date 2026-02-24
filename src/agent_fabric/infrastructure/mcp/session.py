"""MCP session manager: connect to an MCP server, list tools, and call tools."""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from typing import Any, Dict, List

from agent_fabric.config.schema import MCPServerConfig
from agent_fabric.infrastructure.mcp.converter import mcp_tool_to_openai_def

logger = logging.getLogger(__name__)

# Top-level imports with fallback so the module is importable even when the
# optional 'mcp' package is not installed.  Actual usage without the package
# installed will raise ImportError inside connect() with a clear message.
try:
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client, StdioServerParameters
    from mcp.client.sse import sse_client
    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False
    ClientSession = None       # type: ignore[assignment,misc]
    stdio_client = None        # type: ignore[assignment]
    sse_client = None          # type: ignore[assignment]
    StdioServerParameters = None  # type: ignore[assignment,misc]


class MCPSessionManager:
    """Manages the lifecycle of one MCP server connection.

    Usage::

        mgr = MCPSessionManager(config)
        await mgr.connect()
        tools = await mgr.list_tools()           # OpenAI-format defs
        result = await mgr.call_tool("mcp__name__my_tool", {"arg": "val"})
        await mgr.disconnect()

    All tool names are prefixed ``mcp__<server_name>__<tool_name>`` to avoid
    collisions with native pack tools.
    """

    def __init__(self, config: MCPServerConfig) -> None:
        self._config = config
        self._session: Any = None
        self._stack: AsyncExitStack = AsyncExitStack()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Open transport, enter ClientSession, and call initialize()."""
        if not _MCP_AVAILABLE:
            raise ImportError(
                "The 'mcp' package is required for MCP server support. "
                "Install with: pip install agent-fabric[mcp]"
            )

        if self._config.transport == "stdio":
            params = StdioServerParameters(
                command=self._config.command,
                args=self._config.args,
                env=self._config.env,
            )
            read, write = await self._stack.enter_async_context(
                stdio_client(params)
            )
        else:  # sse
            read, write = await self._stack.enter_async_context(
                sse_client(self._config.url, headers=self._config.headers)
            )

        self._session = await self._stack.enter_async_context(
            ClientSession(read, write)
        )
        await self._session.initialize()
        logger.debug(
            "MCPSessionManager: connected to %r (transport=%s)",
            self._config.name, self._config.transport,
        )

    async def disconnect(self) -> None:
        """Close the exit stack, terminating the server connection."""
        await self._stack.aclose()
        self._session = None
        logger.debug("MCPSessionManager: disconnected from %r", self._config.name)

    # ------------------------------------------------------------------
    # Tool interface
    # ------------------------------------------------------------------

    async def list_tools(self) -> List[Dict[str, Any]]:
        """Return OpenAI-format tool definitions for all tools on this server.

        Tool names are prefixed ``mcp__<server_name>__<tool_name>``.
        """
        result = await self._session.list_tools()
        return [
            mcp_tool_to_openai_def(
                f"mcp__{self._config.name}__{tool.name}", tool
            )
            for tool in result.tools
        ]

    async def call_tool(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Call a prefixed tool on this server.

        Strips the ``mcp__<name>__`` prefix before forwarding to the server.
        Returns ``{"result": <text>}`` on success or ``{"error": <text>}`` on
        failure (``isError=True`` or empty content).
        """
        prefix = f"mcp__{self._config.name}__"
        bare_name = tool_name[len(prefix):]

        result = await self._session.call_tool(bare_name, args)

        if result.isError:
            content_text = result.content[0].text if result.content else "unknown error"
            logger.warning(
                "MCPSessionManager: tool %r on server %r returned isError=True: %s",
                bare_name, self._config.name, content_text,
            )
            return {"error": content_text}

        if not result.content:
            return {"result": ""}

        return {"result": result.content[0].text}

    def owns_tool(self, name: str) -> bool:
        """Return True if ``name`` belongs to this server's namespace."""
        return name.startswith(f"mcp__{self._config.name}__")
