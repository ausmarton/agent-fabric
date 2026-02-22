"""Minimal OpenAI-compatible mock server for E2E tests. Returns a single 'final' response."""
from __future__ import annotations

import json
from contextlib import asynccontextmanager

from fastapi import FastAPI

FINAL_CONTENT = json.dumps({
    "action": "final",
    "summary": "E2E test run completed.",
    "artifacts": [],
    "next_steps": [],
    "notes": "",
})


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # no cleanup needed


app = FastAPI(title="mock-llm", lifespan=lifespan)


@app.get("/")
def root():
    return {"ok": True}


@app.post("/v1/chat/completions")
async def chat_completions(request: dict):
    """OpenAI-compatible response so the fabric workflow exits after one round."""
    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": FINAL_CONTENT},
                "finish_reason": "stop",
            }
        ],
        "model": request.get("model", "mock"),
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
