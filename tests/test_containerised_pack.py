"""Tests for ContainerisedSpecialistPack (P6-3).

Unit tests mock subprocess.run and are always part of fast CI.
Integration tests are marked @pytest.mark.podman and skipped when Podman
is not in PATH.

Run integration tests with:
    pytest tests/test_containerised_pack.py -k podman -v
"""
from __future__ import annotations

import shutil
import subprocess
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from agent_fabric.config.schema import FabricConfig, ModelConfig, SpecialistConfig
from agent_fabric.infrastructure.specialists.containerised import ContainerisedSpecialistPack
from agent_fabric.infrastructure.specialists.registry import ConfigSpecialistRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeInnerPack:
    """Minimal inner SpecialistPack for unit tests."""

    specialist_id = "engineering"
    system_prompt = "You are an engineer."
    finish_tool_name = "finish_task"
    finish_required_fields: List[str] = ["summary"]
    tool_definitions: List[Dict[str, Any]] = [
        {"type": "function", "function": {"name": "shell"}},
        {"type": "function", "function": {"name": "read_file"}},
        {"type": "function", "function": {
            "name": "finish_task",
            "parameters": {"required": ["summary"]},
        }},
    ]

    aopen = AsyncMock()
    aclose = AsyncMock()

    async def execute_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if name == "read_file":
            return {"content": "hello"}
        return {"stdout": f"native:{name}"}


def _make_pack(workspace: str = "/tmp/ws") -> ContainerisedSpecialistPack:
    return ContainerisedSpecialistPack(
        inner=_FakeInnerPack(),
        container_image="python:3.12-slim",
        workspace_path=workspace,
    )


def _successful_podman_run(container_id: str = "abc123def456") -> MagicMock:
    """Returns a mock subprocess.CompletedProcess for a successful 'podman run -d'."""
    m = MagicMock()
    m.returncode = 0
    m.stdout = container_id + "\n"
    m.stderr = ""
    return m


def _successful_podman_exec(stdout: str = "ok", returncode: int = 0) -> MagicMock:
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = ""
    return m


def _successful_podman_stop() -> MagicMock:
    m = MagicMock()
    m.returncode = 0
    m.stdout = ""
    m.stderr = ""
    return m


# ---------------------------------------------------------------------------
# Protocol property pass-through (sync, no subprocess needed)
# ---------------------------------------------------------------------------


def test_properties_forwarded_to_inner():
    """specialist_id, system_prompt, finish_tool_name, finish_required_fields forwarded."""
    pack = _make_pack()
    assert pack.specialist_id == "engineering"
    assert pack.system_prompt == "You are an engineer."
    assert pack.finish_tool_name == "finish_task"
    assert pack.finish_required_fields == ["summary"]


def test_tool_definitions_forwarded_to_inner():
    """tool_definitions come from the inner pack unchanged."""
    pack = _make_pack()
    names = {td["function"]["name"] for td in pack.tool_definitions}
    assert "shell" in names
    assert "read_file" in names
    assert "finish_task" in names


# ---------------------------------------------------------------------------
# aopen — unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aopen_starts_container_with_correct_podman_run_args():
    """aopen() calls 'podman run -d --rm -v <ws>:/workspace <image> sleep infinity'."""
    pack = _make_pack(workspace="/my/workspace")
    with patch("subprocess.run", return_value=_successful_podman_run()) as mock_run:
        await pack.aopen()

    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args[0] == "podman"
    assert "run" in args
    assert "-d" in args
    assert "--rm" in args
    assert "-v" in args
    assert "/my/workspace:/workspace:Z" in args
    assert "python:3.12-slim" in args
    assert args[-2:] == ["sleep", "infinity"]


@pytest.mark.asyncio
async def test_aopen_stores_container_id():
    """aopen() strips trailing whitespace and stores the container ID."""
    pack = _make_pack()
    with patch("subprocess.run", return_value=_successful_podman_run("deadbeef1234\n")):
        await pack.aopen()
    assert pack._container_id == "deadbeef1234"


@pytest.mark.asyncio
async def test_aopen_calls_inner_aopen():
    """aopen() calls inner.aopen() after starting the container."""
    inner = _FakeInnerPack()
    inner.aopen = AsyncMock()
    pack = ContainerisedSpecialistPack(inner, "python:3.12-slim", "/tmp")
    with patch("subprocess.run", return_value=_successful_podman_run()):
        await pack.aopen()
    inner.aopen.assert_awaited_once()


@pytest.mark.asyncio
async def test_aopen_raises_runtime_error_when_podman_not_found():
    """aopen() raises RuntimeError with a clear message when podman is not in PATH."""
    pack = _make_pack()
    with patch("subprocess.run", side_effect=FileNotFoundError("podman not found")):
        with pytest.raises(RuntimeError, match="podman is not installed"):
            await pack.aopen()


@pytest.mark.asyncio
async def test_aopen_raises_runtime_error_on_podman_nonzero_exit():
    """aopen() raises RuntimeError when 'podman run' returns a non-zero exit code."""
    bad_result = MagicMock()
    bad_result.returncode = 125
    bad_result.stdout = ""
    bad_result.stderr = "Error: image not found"
    pack = _make_pack()
    with patch("subprocess.run", return_value=bad_result):
        with pytest.raises(RuntimeError, match="Failed to start Podman container"):
            await pack.aopen()


# ---------------------------------------------------------------------------
# aclose — unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aclose_calls_inner_aclose():
    """aclose() always calls inner.aclose()."""
    inner = _FakeInnerPack()
    inner.aclose = AsyncMock()
    pack = ContainerisedSpecialistPack(inner, "python:3.12-slim", "/tmp")
    # Don't call aopen — just test aclose directly.
    await pack.aclose()
    inner.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_aclose_stops_container():
    """aclose() calls 'podman stop <container_id>' after inner.aclose()."""
    pack = _make_pack()
    with patch("subprocess.run", return_value=_successful_podman_run("mycontainer")) as mock_run:
        await pack.aopen()

    with patch("subprocess.run", return_value=_successful_podman_stop()) as mock_stop:
        await pack.aclose()

    stop_args = mock_stop.call_args[0][0]
    assert stop_args == ["podman", "stop", "mycontainer"]


@pytest.mark.asyncio
async def test_aclose_clears_container_id():
    """aclose() sets _container_id to None after stopping."""
    pack = _make_pack()
    with patch("subprocess.run", return_value=_successful_podman_run("x")):
        await pack.aopen()
    with patch("subprocess.run", return_value=_successful_podman_stop()):
        await pack.aclose()
    assert pack._container_id is None


@pytest.mark.asyncio
async def test_aclose_ignores_stop_failure():
    """aclose() does not raise if 'podman stop' fails."""
    pack = _make_pack()
    with patch("subprocess.run", return_value=_successful_podman_run("x")):
        await pack.aopen()
    # podman stop raises — must not propagate
    with patch("subprocess.run", side_effect=RuntimeError("stop failed")):
        await pack.aclose()  # should not raise


@pytest.mark.asyncio
async def test_aclose_noop_when_not_opened():
    """aclose() is safe to call without a prior aopen() (no container_id)."""
    pack = _make_pack()
    # No subprocess call should happen for stop since there's no container.
    with patch("subprocess.run") as mock_run:
        await pack.aclose()
    mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# execute_tool — shell interception (unit tests)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shell_tool_uses_podman_exec():
    """execute_tool('shell') runs via 'podman exec -w /workspace <id> <cmd>'."""
    pack = _make_pack()
    with patch("subprocess.run", return_value=_successful_podman_run("cid123")):
        await pack.aopen()

    with patch("subprocess.run", return_value=_successful_podman_exec("hello")) as mock_run:
        result = await pack.execute_tool("shell", {"cmd": ["python", "--version"]})

    exec_args = mock_run.call_args[0][0]
    assert exec_args[0] == "podman"
    assert "exec" in exec_args
    assert "-w" in exec_args
    assert "/workspace" in exec_args
    assert "cid123" in exec_args
    assert exec_args[-2:] == ["python", "--version"]
    assert result["returncode"] == 0
    assert result["stdout"] == "hello"


@pytest.mark.asyncio
async def test_shell_tool_disallowed_command_raises_permission_error():
    """execute_tool('shell') raises PermissionError for a command not in the allowlist."""
    pack = _make_pack()
    with patch("subprocess.run", return_value=_successful_podman_run("cid")):
        await pack.aopen()

    with pytest.raises(PermissionError, match="not allowed"):
        await pack.execute_tool("shell", {"cmd": ["curl", "http://evil.example.com"]})


@pytest.mark.asyncio
async def test_shell_tool_empty_command_raises_value_error():
    """execute_tool('shell') raises ValueError for an empty cmd list."""
    pack = _make_pack()
    with patch("subprocess.run", return_value=_successful_podman_run("cid")):
        await pack.aopen()

    with pytest.raises(ValueError, match="Empty command"):
        await pack.execute_tool("shell", {"cmd": []})


@pytest.mark.asyncio
async def test_shell_tool_returns_error_dict_when_no_container():
    """execute_tool('shell') returns an error dict if called before aopen()."""
    pack = _make_pack()
    result = await pack.execute_tool("shell", {"cmd": ["ls"]})
    assert "error" in result
    assert "aopen" in result["error"]


@pytest.mark.asyncio
async def test_shell_tool_timeout_returns_error_dict():
    """execute_tool('shell') returns an error dict with timeout message on TimeoutExpired."""
    pack = _make_pack()
    with patch("subprocess.run", return_value=_successful_podman_run("cid")):
        await pack.aopen()

    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="podman", timeout=5)):
        result = await pack.execute_tool("shell", {"cmd": ["python", "slow.py"]})

    assert result["returncode"] == -1
    assert "timed out" in result["stderr"]


# ---------------------------------------------------------------------------
# execute_tool — non-shell delegation (unit tests)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_shell_tool_delegates_to_inner_pack():
    """execute_tool() for non-shell tools delegates to the inner pack."""
    pack = _make_pack()
    # No aopen needed — just test delegation.
    result = await pack.execute_tool("read_file", {"path": "foo.txt"})
    assert result == {"content": "hello"}


@pytest.mark.asyncio
async def test_finish_task_not_intercepted():
    """execute_tool() does not intercept finish_task — it goes to the inner pack."""
    pack = _make_pack()
    result = await pack.execute_tool("finish_task", {"summary": "done"})
    # Inner pack returns {"stdout": "native:finish_task"} for unknown tools
    assert "native:finish_task" in result.get("stdout", "")


# ---------------------------------------------------------------------------
# Registry integration (unit tests)
# ---------------------------------------------------------------------------


def test_registry_wraps_pack_with_containerised_when_container_image_set():
    """ConfigSpecialistRegistry.get_pack() wraps with ContainerisedSpecialistPack."""
    config = FabricConfig(
        models={"quality": ModelConfig(base_url="http://localhost:11434/v1", model="test")},
        specialists={
            "engineering": SpecialistConfig(
                description="eng",
                keywords=[],
                workflow="engineering",
                container_image="python:3.12-slim",
            )
        },
    )
    registry = ConfigSpecialistRegistry(config)
    pack = registry.get_pack("engineering", "/tmp", network_allowed=False)
    assert isinstance(pack, ContainerisedSpecialistPack)
    assert pack._image == "python:3.12-slim"


def test_registry_no_wrap_when_container_image_not_set():
    """ConfigSpecialistRegistry.get_pack() returns plain pack when container_image is None."""
    from agent_fabric.config import load_config
    registry = ConfigSpecialistRegistry(load_config())
    pack = registry.get_pack("engineering", "/tmp", network_allowed=False)
    assert not isinstance(pack, ContainerisedSpecialistPack)


def test_registry_container_image_wraps_after_mcp():
    """When both mcp_servers and container_image are set, pack is ContainerisedSpecialistPack(MCPAugmentedPack(inner))."""
    import sys
    from unittest.mock import MagicMock

    # Inject mock mcp modules
    sys.modules.setdefault("mcp", MagicMock())
    sys.modules.setdefault("mcp.client", MagicMock())
    sys.modules.setdefault("mcp.client.stdio", MagicMock())
    sys.modules.setdefault("mcp.client.sse", MagicMock())

    from agent_fabric.config.schema import MCPServerConfig
    from agent_fabric.infrastructure.mcp.augmented_pack import MCPAugmentedPack

    config = FabricConfig(
        models={"quality": ModelConfig(base_url="http://localhost:11434/v1", model="test")},
        specialists={
            "engineering": SpecialistConfig(
                description="eng",
                keywords=[],
                workflow="engineering",
                mcp_servers=[MCPServerConfig(name="fs", transport="stdio", command="npx", args=[])],
                container_image="python:3.12-slim",
            )
        },
    )
    registry = ConfigSpecialistRegistry(config)
    pack = registry.get_pack("engineering", "/tmp", network_allowed=False)
    # Outermost layer: ContainerisedSpecialistPack
    assert isinstance(pack, ContainerisedSpecialistPack)
    # Inner layer: MCPAugmentedPack
    assert isinstance(pack._inner, MCPAugmentedPack)


# ---------------------------------------------------------------------------
# Podman integration tests (require real Podman)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def skip_if_podman_unavailable():
    """Skip if Podman is not in PATH."""
    if shutil.which("podman") is None:
        pytest.skip("podman not in PATH — install Podman to run podman integration tests")


@pytest.fixture(scope="module")
def podman_image():
    """Return a small, available image; skip if none is available."""
    for image in (
        "alpine",
        "busybox",
        "python:3.12-slim",
        "python:3.11-slim",
        "python:3.10-slim",
    ):
        result = subprocess.run(
            ["podman", "image", "exists", image],
            capture_output=True,
        )
        if result.returncode == 0:
            return image
    pytest.skip(
        "No suitable container image found (alpine, busybox, python:3.*-slim). "
        "Pull one with: podman pull alpine"
    )


@pytest.mark.podman
@pytest.mark.asyncio
async def test_podman_aopen_starts_real_container(
    tmp_path,
    skip_if_podman_unavailable,
    podman_image,
):
    """aopen() starts a real Podman container; aclose() stops it."""
    pack = ContainerisedSpecialistPack(
        inner=_FakeInnerPack(),
        container_image=podman_image,
        workspace_path=str(tmp_path),
    )
    try:
        await pack.aopen()
        assert pack._container_id, "Expected a non-empty container ID after aopen()"
        # Verify it's actually running
        result = subprocess.run(
            ["podman", "inspect", "--format", "{{.State.Status}}", pack._container_id],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "running" in result.stdout.lower()
    finally:
        await pack.aclose()


@pytest.mark.podman
@pytest.mark.asyncio
async def test_podman_shell_exec_in_container(
    tmp_path,
    skip_if_podman_unavailable,
    podman_image,
):
    """execute_tool('shell') executes inside the container (runs 'sh -c echo')."""
    pack = ContainerisedSpecialistPack(
        inner=_FakeInnerPack(),
        container_image=podman_image,
        workspace_path=str(tmp_path),
    )
    try:
        await pack.aopen()
        result = await pack.execute_tool("shell", {"cmd": ["sh", "-c", "echo hello-from-container"]})
    finally:
        await pack.aclose()

    assert result["returncode"] == 0
    assert "hello-from-container" in result["stdout"]


@pytest.mark.podman
@pytest.mark.asyncio
async def test_podman_workspace_mount(
    tmp_path,
    skip_if_podman_unavailable,
    podman_image,
):
    """Files written on the host are visible in the container at /workspace."""
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("fabric-container-test")

    pack = ContainerisedSpecialistPack(
        inner=_FakeInnerPack(),
        container_image=podman_image,
        workspace_path=str(tmp_path),
    )
    try:
        await pack.aopen()
        result = await pack.execute_tool(
            "shell",
            {"cmd": ["sh", "-c", "cat /workspace/sentinel.txt"]},
        )
    finally:
        await pack.aclose()

    assert result["returncode"] == 0
    assert "fabric-container-test" in result["stdout"]


@pytest.mark.podman
@pytest.mark.asyncio
async def test_podman_aclose_stops_container(
    tmp_path,
    skip_if_podman_unavailable,
    podman_image,
):
    """After aclose(), the container no longer exists."""
    pack = ContainerisedSpecialistPack(
        inner=_FakeInnerPack(),
        container_image=podman_image,
        workspace_path=str(tmp_path),
    )
    await pack.aopen()
    container_id = pack._container_id
    assert container_id

    await pack.aclose()
    assert pack._container_id is None

    # Container should be gone (inspect returns non-zero or shows "exited"/"removing")
    result = subprocess.run(
        ["podman", "inspect", "--format", "{{.State.Status}}", container_id],
        capture_output=True, text=True,
    )
    # Either inspect fails (container removed by --rm) or shows stopped state
    if result.returncode == 0:
        assert "running" not in result.stdout.lower()
