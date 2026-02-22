"""HTTP API: FastAPI app wired to execute_task (new architecture)."""

from __future__ import annotations

import os

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional

from agent_fabric.application.execute_task import execute_task
from agent_fabric.config import load_config
from agent_fabric.domain import Task
from agent_fabric.infrastructure.llm_discovery import resolve_llm
from agent_fabric.infrastructure.ollama import OllamaChatClient
from agent_fabric.infrastructure.workspace import FileSystemRunRepository
from agent_fabric.infrastructure.specialists import ConfigSpecialistRegistry

app = FastAPI(title="agent-fabric", version="0.1.0")


def _workspace_root() -> str:
    return os.environ.get("FABRIC_WORKSPACE", ".fabric")


class RunRequest(BaseModel):
    prompt: str
    pack: Optional[str] = None
    model_key: str = "quality"
    network_allowed: bool = True


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/run")
async def run(req: RunRequest):
    config = load_config()
    try:
        resolved = resolve_llm(config, req.model_key)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    chat_client = OllamaChatClient(
        base_url=resolved.base_url,
        api_key=resolved.model_config.api_key,
        timeout_s=resolved.model_config.timeout_s,
    )
    run_repository = FileSystemRunRepository(workspace_root=_workspace_root())
    specialist_registry = ConfigSpecialistRegistry(config)

    task = Task(
        prompt=req.prompt,
        specialist_id=req.pack.strip() if req.pack else None,
        model_key=req.model_key,
        network_allowed=req.network_allowed,
    )
    try:
        result = await execute_task(
            task,
            chat_client=chat_client,
            run_repository=run_repository,
            specialist_registry=specialist_registry,
            config=config,
            resolved_model_cfg=resolved.model_config,
            workspace_root=_workspace_root(),
            max_steps=40,
        )
    except httpx.ConnectError as e:
        raise HTTPException(
            status_code=503,
            detail=f"LLM server unreachable ({resolved.base_url}): {e}. Install/start your backend or set local_llm_ensure_available: false.",
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(
                status_code=503,
                detail=f"Model not found (404). Pull: ollama pull {resolved.model} or set FABRIC_CONFIG_PATH.",
            )
        raise HTTPException(
            status_code=503,
            detail=f"LLM server error ({resolved.base_url}): {e.response.status_code}. Check backend and model.",
        )
    # Response shape compatible with old API: _meta + payload
    out = dict(result.payload)
    out["_meta"] = {
        "pack": result.specialist_id,
        "run_dir": result.run_dir,
        "workspace": result.workspace_path,
        "model": result.model_name,
        "run_id": result.run_id.value,
    }
    return out
