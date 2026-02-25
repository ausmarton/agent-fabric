"""MCP (Model Context Protocol) support for agentic-concierge.

This package requires the optional ``mcp`` dependency::

    pip install agentic-concierge[mcp]

Exports:
    MCPSessionManager  — manages one MCP server connection
    MCPAugmentedPack   — wraps a SpecialistPack with MCP tool servers
"""

from agentic_concierge.infrastructure.mcp.session import MCPSessionManager
from agentic_concierge.infrastructure.mcp.augmented_pack import MCPAugmentedPack

__all__ = ["MCPSessionManager", "MCPAugmentedPack"]
