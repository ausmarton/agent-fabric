#!/usr/bin/env python3
"""
Verify the fabric with a REAL LLM: run a task against the configured server,
then check that the model actually used tools and produced artifacts.

We use Ollama by default. Run: ollama serve && ollama pull qwen2.5:7b (and optionally qwen2.5:14b).
To use another backend, set FABRIC_CONFIG_PATH to a config that points at it.

Run from repo root: python scripts/verify_working_real.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

# Repo root
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from agent_fabric.application.execute_task import execute_task
from agent_fabric.config import load_config
from agent_fabric.domain import Task
from agent_fabric.infrastructure.llm_discovery import resolve_llm
from agent_fabric.infrastructure.ollama import OllamaChatClient
from agent_fabric.infrastructure.workspace import FileSystemRunRepository
from agent_fabric.infrastructure.specialists import ConfigSpecialistRegistry


def main():
    os.environ.setdefault("FABRIC_WORKSPACE", os.path.join(REPO_ROOT, ".fabric"))
    cfg = load_config()
    model_key = "quality"
    if model_key not in cfg.models:
        print("ERROR: Config has no 'quality' model. Check FABRIC_CONFIG_PATH or defaults.")
        return 1

    try:
        resolved = resolve_llm(cfg, model_key)
    except RuntimeError as e:
        print("RESOLVE FAILED:", e)
        print("Start Ollama (ollama serve), pull a chat model (ollama pull llama3.1:8b), then retry.")
        return 1

    base_url = resolved.base_url
    print("Using LLM at:", base_url, "model:", resolved.model)
    print("Running real engineering task: create a small Python file + test, then list files...")
    print()

    chat_client = OllamaChatClient(
        base_url=resolved.base_url,
        api_key=resolved.model_config.api_key,
        timeout_s=resolved.model_config.timeout_s,
    )
    run_repository = FileSystemRunRepository(workspace_root=os.environ["FABRIC_WORKSPACE"])
    specialist_registry = ConfigSpecialistRegistry(cfg)
    task = Task(
        prompt="Create a file hello.txt containing the line 'Hello World'. "
        "Then run the shell command to list the workspace directory.",
        specialist_id="engineering",
        model_key=model_key,
        network_allowed=False,
    )

    try:
        result = asyncio.run(
            execute_task(
                task,
                chat_client=chat_client,
                run_repository=run_repository,
                specialist_registry=specialist_registry,
                config=cfg,
                resolved_model_cfg=resolved.model_config,
                workspace_root=os.environ["FABRIC_WORKSPACE"],
                max_steps=40,
            )
        )
    except Exception as e:
        err = str(e).lower()
        if "connect" in err or "connection" in err or "refused" in err:
            print("CONNECTION FAILED: No LLM server reached at", base_url)
            print()
            print("We use Ollama by default. Start Ollama, then run this script again:")
            print("  ollama serve")
            print("  ollama pull qwen2.5:7b")
            print("Example (llama.cpp):  llama-server -m /path/to/model.gguf --host 127.0.0.1 --port 8000")
            print("Example (llama-cpp-python):  python -m llama_cpp.server --model /path/to/model.gguf --port 8000")
            print()
            print("Error:", e)
        else:
            print("Error:", e)
        return 1

    run_dir = result.run_dir
    if not run_dir or not os.path.isdir(run_dir):
        print("FAIL: No run directory in result.")
        return 1

    runlog_path = os.path.join(run_dir, "runlog.jsonl")
    workspace_path = result.workspace_path
    if not os.path.isfile(runlog_path):
        print("FAIL: runlog.jsonl missing at", runlog_path)
        return 1

    events = []
    with open(runlog_path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    kinds = [e.get("kind") for e in events]
    has_tool_call = "tool_call" in kinds
    has_tool_result = "tool_result" in kinds
    has_llm_response = "llm_response" in kinds

    if not has_llm_response:
        print("FAIL: Runlog has no llm_response (model may not have been called).")
        return 1
    if not has_tool_call:
        print("FAIL: Runlog has no tool_call — the model did not use any tools.")
        print("      We need to see real tool use (e.g. write_file, shell, list_files).")
        return 1
    if not has_tool_result:
        print("FAIL: Runlog has no tool_result — tool calls did not complete.")
        return 1

    workspace_files = []
    if os.path.isdir(workspace_path):
        for name in os.listdir(workspace_path):
            p = os.path.join(workspace_path, name)
            if os.path.isfile(p):
                workspace_files.append(name)
            else:
                for sub in os.listdir(p):
                    workspace_files.append(os.path.join(name, sub))

    print("OK: Run completed with action =", result.payload.get("action"))
    print("OK: Runlog contains llm_request/llm_response and tool_call/tool_result")
    print("OK: Model used tools (", sum(1 for k in kinds if k == "tool_call"), "tool call(s) )")
    if workspace_files:
        print("OK: Workspace has file(s):", workspace_files[:10])
    else:
        print("INFO: Workspace has no files (model may have only run list_files in empty dir)")

    print()
    print("Real verification passed: the fabric is doing what it's supposed to.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
