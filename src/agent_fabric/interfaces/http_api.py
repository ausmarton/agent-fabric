"""HTTP API: FastAPI app wired to execute_task."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from agent_fabric.application.execute_task import execute_task
from agent_fabric.config import load_config
from agent_fabric.domain import Task, build_task
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
    logger.info(
        "POST /run prompt=%r pack=%s model=%s network=%s",
        req.prompt[:80], req.pack, req.model_key, req.network_allowed,
    )
    config = load_config()

    # resolve_llm performs blocking I/O (HTTP probes, optional subprocess) so we
    # run it on a thread-pool worker to avoid blocking the event loop.
    try:
        resolved = await asyncio.to_thread(resolve_llm, config, req.model_key)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    chat_client = OllamaChatClient(
        base_url=resolved.base_url,
        api_key=resolved.model_config.api_key,
        timeout_s=resolved.model_config.timeout_s,
    )
    run_repository = FileSystemRunRepository(workspace_root=_workspace_root())
    specialist_registry = ConfigSpecialistRegistry(config)

    task = build_task(req.prompt, req.pack, req.model_key, req.network_allowed)
    try:
        result = await execute_task(
            task,
            chat_client=chat_client,
            run_repository=run_repository,
            specialist_registry=specialist_registry,
            config=config,
            resolved_model_cfg=resolved.model_config,
            max_steps=40,
        )
    except httpx.ConnectError as e:
        raise HTTPException(
            status_code=503,
            detail=(
                f"LLM server unreachable ({resolved.base_url}): {e}. "
                "Install/start your backend or set local_llm_ensure_available: false."
            ),
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(
                status_code=503,
                detail=f"Model not found (404). Pull: ollama pull {resolved.model} or set FABRIC_CONFIG_PATH.",
            )
        raise HTTPException(
            status_code=503,
            detail=f"LLM server error ({resolved.base_url}): {e.response.status_code}.",
        )

    logger.info(
        "POST /run completed run_id=%s pack=%s model=%s",
        result.run_id.value, result.specialist_id, result.model_name,
    )
    out = dict(result.payload)
    out["_meta"] = {
        "pack": result.specialist_id,
        "run_dir": result.run_dir,
        "workspace": result.workspace_path,
        "model": result.model_name,
        "run_id": result.run_id.value,
    }
    return out
