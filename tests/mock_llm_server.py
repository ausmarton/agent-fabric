"""Minimal OpenAI-compatible mock server for E2E tests.

Returns a single ``finish_task`` tool call so the execute-task loop completes
in one round-trip and the test can verify run directory structure and runlog
events (including ``tool_call`` / ``tool_result``).
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager

from fastapi import FastAPI

_FINISH_TASK_ARGUMENTS = json.dumps({
    "summary": "E2E test run completed.",
    "artifacts": [],
    "next_steps": [],
    "notes": "",
})


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="mock-llm", lifespan=lifespan)


@app.get("/")
def root():
    return {"ok": True}


@app.post("/v1/chat/completions")
async def chat_completions(request: dict):
    """Return a finish_task tool call so the fabric loop completes after one step."""
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_mock_1",
                            "type": "function",
                            "function": {
                                "name": "finish_task",
                                "arguments": _FINISH_TASK_ARGUMENTS,
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "model": request.get("model", "mock"),
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
