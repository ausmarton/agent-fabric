"""Tests that implementation aligns with BACKENDS.md and REQUIREMENTS: backend-agnostic, local LLM default, clean lifecycle."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_fabric.application.execute_task import execute_task
from agent_fabric.config import FabricConfig, ModelConfig, load_config
from agent_fabric.config.schema import DEFAULT_CONFIG
from agent_fabric.domain import RunId, RunResult, Task
from agent_fabric.infrastructure.llm_discovery import ResolvedLLM, resolve_llm
from agent_fabric.infrastructure.workspace import FileSystemRunRepository
from agent_fabric.infrastructure.specialists import ConfigSpecialistRegistry


# ---- ChatClient port: execute_task uses only chat() with OpenAI-style args ----


@pytest.mark.asyncio
async def test_execute_task_uses_only_chat_client_chat_with_openai_params(tmp_path):
    """Application layer depends only on ChatClient.chat(messages, model, temperature, top_p, max_tokens)."""
    recorded = []

    class RecordingChatClient:
        async def chat(self, messages, model, temperature=0.1, top_p=0.9, max_tokens=2048):
            recorded.append({
                "messages": messages,
                "model": model,
                "temperature": temperature,
                "top_p": top_p,
                "max_tokens": max_tokens,
            })
            return json.dumps({"action": "final", "summary": "ok", "artifacts": [], "next_steps": [], "notes": ""})

    config = load_config()
    run_repository = FileSystemRunRepository(workspace_root=str(tmp_path))
    specialist_registry = ConfigSpecialistRegistry(config)
    task = Task(prompt="list files", specialist_id="engineering", network_allowed=False)

    await execute_task(
        task,
        chat_client=RecordingChatClient(),
        run_repository=run_repository,
        specialist_registry=specialist_registry,
        config=config,
        workspace_root=str(tmp_path),
        max_steps=5,
    )

    assert len(recorded) >= 1
    first = recorded[0]
    assert "messages" in first and isinstance(first["messages"], list)
    assert first["model"] == config.models["quality"].model
    assert "temperature" in first and "top_p" in first and "max_tokens" in first


# ---- Config: local_llm_ensure_available default and opt-out ----


def test_config_default_ensures_local_llm():
    """REQUIREMENTS FR4.1: local_llm_ensure_available is True by default."""
    assert DEFAULT_CONFIG.local_llm_ensure_available is True
    assert len(DEFAULT_CONFIG.local_llm_start_cmd) >= 1
    assert DEFAULT_CONFIG.local_llm_start_timeout_s > 0


def test_config_base_url_and_model_are_backend_agnostic():
    """Config exposes base_url and model; defaults point at Ollama but any URL/model work."""
    mc = DEFAULT_CONFIG.models["quality"]
    assert mc.base_url.startswith("http")
    assert "/v1" in mc.base_url or mc.base_url.rstrip("/").endswith("11434")
    assert isinstance(mc.model, str) and len(mc.model) > 0
    # Custom config can override to a different backend
    custom = FabricConfig(
        models={"x": ModelConfig(base_url="http://localhost:8000/v1", model="my-model")},
        specialists=DEFAULT_CONFIG.specialists,
    )
    assert custom.models["x"].base_url == "http://localhost:8000/v1"
    assert custom.models["x"].model == "my-model"


# ---- API: resolve_llm used for discovery/selection; ensure_llm only when enabled ----


def test_api_run_calls_resolve_llm():
    """API /run calls resolve_llm so backend and model are discovered/selected (and LLM ensured when enabled)."""
    from agent_fabric.interfaces.http_api import app
    from fastapi.testclient import TestClient

    cfg = FabricConfig(
        models={"q": ModelConfig(base_url="http://127.0.0.1:19999/v1", model="test")},
        specialists=DEFAULT_CONFIG.specialists,
        local_llm_ensure_available=True,
        local_llm_start_cmd=["/bin/true"],
        local_llm_start_timeout_s=2,
    )
    resolved = ResolvedLLM(
        base_url="http://127.0.0.1:19999/v1",
        model="test",
        model_config=ModelConfig(base_url="http://127.0.0.1:19999/v1", model="test"),
    )
    with patch("agent_fabric.interfaces.http_api.load_config", return_value=cfg):
        with patch("agent_fabric.interfaces.http_api.resolve_llm", return_value=resolved) as resolve:
            with patch("agent_fabric.interfaces.http_api.execute_task", new_callable=AsyncMock) as run_task:
                run_task.return_value = RunResult(
                    run_id=RunId("test-id"),
                    run_dir="/tmp/r",
                    workspace_path="/tmp/r/workspace",
                    specialist_id="engineering",
                    model_name="test",
                    payload={"action": "final", "summary": "ok", "artifacts": [], "next_steps": [], "notes": ""},
                )
                client = TestClient(app)
                r = client.post("/run", json={"prompt": "hi", "pack": "engineering", "model_key": "q"})
                assert r.status_code == 200
                resolve.assert_called_once()
                assert resolve.call_args[0][1] == "q"


def test_api_run_skips_ensure_llm_available_when_opted_out():
    """When local_llm_ensure_available is False, resolve_llm does not call ensure_llm_available."""
    from agent_fabric.infrastructure.llm_bootstrap import ensure_llm_available
    from agent_fabric.interfaces.http_api import app
    from fastapi.testclient import TestClient

    cfg = FabricConfig(
        models={"q": ModelConfig(base_url="http://127.0.0.1:19998/v1", model="test")},
        specialists=DEFAULT_CONFIG.specialists,
        local_llm_ensure_available=False,
        local_llm_start_cmd=[],
    )
    with patch("agent_fabric.interfaces.http_api.load_config", return_value=cfg):
        with patch("agent_fabric.infrastructure.llm_bootstrap.ensure_llm_available") as ensure:
            with patch("agent_fabric.infrastructure.llm_discovery.discover_ollama_models", return_value=[{"name": "test", "model": "test"}]):
                with patch("agent_fabric.interfaces.http_api.execute_task", new_callable=AsyncMock) as run_task:
                    run_task.return_value = RunResult(
                        run_id=RunId("test-id"),
                        run_dir="/tmp/r",
                        workspace_path="/tmp/r/workspace",
                        specialist_id="engineering",
                        model_name="test",
                        payload={"action": "final", "summary": "ok", "artifacts": [], "next_steps": [], "notes": ""},
                    )
                    client = TestClient(app)
                    r = client.post("/run", json={"prompt": "hi", "pack": "engineering", "model_key": "q"})
                    assert r.status_code == 200
                    ensure.assert_not_called()


# ---- Run directory: under workspace_root only, no stray paths ----


def test_run_directory_created_under_workspace_root_only(tmp_path):
    """Run dir and workspace are created only under workspace_root/runs/<id>/; no temp files elsewhere."""
    from agent_fabric.infrastructure.workspace.run_directory import create_run_directory

    root = Path(tmp_path) / "fabric_root"
    root.mkdir(parents=True)
    run_id, run_dir, workspace_path = create_run_directory(root)

    assert run_dir.startswith(str(root))
    assert "runs" in run_dir
    assert run_id.value in run_dir
    assert Path(run_dir).is_dir()
    assert Path(workspace_path).is_dir()
    assert Path(workspace_path).parent == Path(run_dir)
    assert (Path(run_dir) / "workspace").resolve() == Path(workspace_path).resolve()
