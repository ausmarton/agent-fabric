"""Tests for MCP integration in ConfigSpecialistRegistry (P5-5).

Verifies that get_pack() wraps the inner pack with MCPAugmentedPack when
mcp_servers is non-empty, and passes through unchanged when it's empty.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

# Inject mock mcp modules so the mcp optional dep isn't needed.
_mock_mcp = MagicMock()
sys.modules.setdefault("mcp", _mock_mcp)
sys.modules.setdefault("mcp.client", MagicMock())
sys.modules.setdefault("mcp.client.stdio", MagicMock())
sys.modules.setdefault("mcp.client.sse", MagicMock())

from agent_fabric.config import load_config  # noqa: E402
from agent_fabric.config.schema import FabricConfig, MCPServerConfig, SpecialistConfig  # noqa: E402
from agent_fabric.infrastructure.mcp.augmented_pack import MCPAugmentedPack  # noqa: E402
from agent_fabric.infrastructure.specialists import ConfigSpecialistRegistry  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_model():
    from agent_fabric.config.schema import ModelConfig
    return ModelConfig(base_url="http://localhost:11434/v1", model="test-model")


def _config_with_mcp(mcp_servers: list) -> FabricConfig:
    return FabricConfig(
        models={"q": _minimal_model()},
        specialists={
            "engineering": SpecialistConfig(
                description="Engineering pack with MCP.",
                keywords=["build"],
                workflow="engineering",
                mcp_servers=mcp_servers,
            ),
        },
    )


def _stdio_server(name: str = "github") -> MCPServerConfig:
    return MCPServerConfig(name=name, transport="stdio", command="npx", args=["-y", "server"])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_get_pack_returns_plain_pack_when_no_mcp_servers():
    """get_pack() returns an unwrapped pack when mcp_servers is empty."""
    registry = ConfigSpecialistRegistry(load_config())
    pack = registry.get_pack("engineering", "/tmp", network_allowed=False)
    assert not isinstance(pack, MCPAugmentedPack)


def test_get_pack_returns_mcp_augmented_pack_when_mcp_servers_non_empty():
    """get_pack() returns MCPAugmentedPack when mcp_servers is non-empty."""
    config = _config_with_mcp([_stdio_server("github")])
    registry = ConfigSpecialistRegistry(config)
    pack = registry.get_pack("engineering", "/tmp", network_allowed=False)
    assert isinstance(pack, MCPAugmentedPack)


def test_mcp_augmented_pack_wraps_inner_pack_properties():
    """MCPAugmentedPack from get_pack() forwards specialist_id and finish_tool_name."""
    config = _config_with_mcp([_stdio_server()])
    registry = ConfigSpecialistRegistry(config)
    pack = registry.get_pack("engineering", "/tmp", network_allowed=False)
    assert pack.specialist_id == "engineering"
    assert pack.finish_tool_name == "finish_task"


def test_mcp_sessions_created_from_config():
    """get_pack() creates one MCPSessionManager per configured MCP server."""
    config = _config_with_mcp([
        _stdio_server("github"),
        _stdio_server("jira"),
    ])
    registry = ConfigSpecialistRegistry(config)
    pack = registry.get_pack("engineering", "/tmp", network_allowed=False)
    assert isinstance(pack, MCPAugmentedPack)
    # Two sessions were attached.
    assert len(pack._sessions) == 2


def test_get_pack_raises_runtime_error_when_mcp_not_installed():
    """get_pack() raises RuntimeError when mcp_servers is set but 'mcp' is not installed."""
    config = _config_with_mcp([_stdio_server()])
    registry = ConfigSpecialistRegistry(config)
    # Simulate mcp import failing inside the registry's conditional import.
    with patch.dict("sys.modules", {"agent_fabric.infrastructure.mcp": None}):
        with pytest.raises(RuntimeError, match="mcp.*package.*not installed"):
            registry.get_pack("engineering", "/tmp", network_allowed=False)


def test_get_pack_with_custom_builder_and_mcp_servers():
    """Custom builder + mcp_servers: pack is built by builder then wrapped."""
    from typing import Any, Dict, List

    class _CustomPack:
        specialist_id = "custom"
        system_prompt = "custom"
        finish_tool_name = "finish_task"
        finish_required_fields: List[str] = []
        tool_definitions: List[Dict[str, Any]] = []

        async def execute_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
            return {}

        async def aopen(self) -> None: pass
        async def aclose(self) -> None: pass

    import sys
    import types
    mod = types.ModuleType("_test_custom_mcp_builder_mod")
    mod.build = lambda ws, net: _CustomPack()  # type: ignore[attr-defined]
    sys.modules["_test_custom_mcp_builder_mod"] = mod

    try:
        config = FabricConfig(
            models={"q": _minimal_model()},
            specialists={
                "custom": SpecialistConfig(
                    description="Custom with MCP.",
                    keywords=[],
                    workflow="custom",
                    builder="_test_custom_mcp_builder_mod:build",
                    mcp_servers=[_stdio_server("srv")],
                ),
            },
        )
        registry = ConfigSpecialistRegistry(config)
        pack = registry.get_pack("custom", "/tmp", network_allowed=False)
        assert isinstance(pack, MCPAugmentedPack)
        assert isinstance(pack._inner, _CustomPack)
    finally:
        del sys.modules["_test_custom_mcp_builder_mod"]
