#!/usr/bin/env python3
"""
Verify the fabric works end-to-end: start a mock OpenAI-compatible server,
run execute_task, and assert run dir + runlog + workspace exist.
Run from repo root: python scripts/verify_working.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import threading
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import uvicorn
from agent_fabric.application.execute_task import execute_task
from agent_fabric.config import DEFAULT_CONFIG, FabricConfig, ModelConfig
from agent_fabric.domain import Task
from agent_fabric.infrastructure.ollama import OllamaChatClient
from agent_fabric.infrastructure.workspace import FileSystemRunRepository
from agent_fabric.infrastructure.specialists import ConfigSpecialistRegistry

from tests.mock_llm_server import app as mock_llm_app

PORT = 18997


def main():
    print("Starting mock LLM server on http://127.0.0.1:%s ..." % PORT)
    base_url = "http://127.0.0.1:%s/v1" % PORT
    config = FabricConfig(
        models={"quality": ModelConfig(base_url=base_url, model="mock", timeout_s=10.0)},
        specialists=DEFAULT_CONFIG.specialists,
    )
    workspace_root = os.path.join(REPO_ROOT, ".fabric")
    run_repository = FileSystemRunRepository(workspace_root=workspace_root)
    specialist_registry = ConfigSpecialistRegistry(config)
    chat_client = OllamaChatClient(base_url=base_url, timeout_s=10.0)

    def run_server():
        uvicorn.run(mock_llm_app, host="127.0.0.1", port=PORT, log_level="warning")

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    time.sleep(1.5)

    print("Running fabric task: 'Create a hello world file' (pack=engineering) ...")
    task = Task(prompt="Create a hello world file", specialist_id="engineering", network_allowed=False)
    result = asyncio.run(
        execute_task(
            task,
            chat_client=chat_client,
            run_repository=run_repository,
            specialist_registry=specialist_registry,
            config=config,
            workspace_root=workspace_root,
            max_steps=40,
        )
    )

    assert result.payload.get("action") == "final", "Expected action=final"
    run_dir = result.run_dir
    workspace = result.workspace_path
    assert os.path.isfile(os.path.join(run_dir, "runlog.jsonl")), "runlog.jsonl missing"
    assert os.path.isdir(workspace), "workspace missing"

    print("OK: Result action =", result.payload.get("action"))
    print("OK: Pack =", result.specialist_id)
    print("OK: Run dir =", run_dir)
    print("OK: runlog.jsonl and workspace exist")
    with open(os.path.join(run_dir, "runlog.jsonl")) as f:
        lines = f.readlines()
    print("OK: runlog has %d event(s)" % len(lines))
    print("\nFabric is working.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
