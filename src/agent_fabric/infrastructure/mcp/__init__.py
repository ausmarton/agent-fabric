"""MCP (Model Context Protocol) support for agent-fabric.

This package requires the optional ``mcp`` dependency::

    pip install agent-fabric[mcp]

Exports:
    MCPSessionManager  — manages one MCP server connection
    MCPAugmentedPack   — wraps a SpecialistPack with MCP tool servers
"""

from agent_fabric.infrastructure.mcp.session import MCPSessionManager
from agent_fabric.infrastructure.mcp.augmented_pack import MCPAugmentedPack

__all__ = ["MCPSessionManager", "MCPAugmentedPack"]
