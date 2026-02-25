"""Tests for the per-IP sliding-window rate limiting middleware.

The middleware is active only when the FABRIC_RATE_LIMIT environment variable
is set to a positive integer (requests per minute).  When inactive, all
requests pass through unchanged.

Middleware order (last registered = outermost):
  _rate_limit_middleware  (registered 2nd → runs first)
  _auth_middleware        (registered 1st → runs second)
  handler

This means:
- A rate-limited request returns 429 before reaching auth or the handler.
- A non-rate-limited request continues to auth (which we can short-circuit
  with FABRIC_API_KEY set so the handler is never reached).
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@contextmanager
def _client(rate_limit: str | None = None, api_key: str = "test-secret"):
    """Return a TestClient with rate-limiting and auth optionally configured.

    ``api_key`` is set by default so auth middleware rejects requests before
    they reach the handler — this avoids any real Ollama / LLM connections.
    """
    from agent_fabric.interfaces import http_api
    http_api._rate_limit_windows.clear()

    from agent_fabric.interfaces.http_api import app
    env: dict = {"FABRIC_API_KEY": api_key}
    if rate_limit is not None:
        env["FABRIC_RATE_LIMIT"] = rate_limit
    with patch.dict(os.environ, env, clear=False):
        if rate_limit is None:
            os.environ.pop("FABRIC_RATE_LIMIT", None)
        yield TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Rate limiting disabled (no FABRIC_RATE_LIMIT)
# ---------------------------------------------------------------------------

def test_health_accessible_no_rate_limit():
    """/health passes when FABRIC_RATE_LIMIT is not set."""
    with _client() as client:
        r = client.get("/health")
    assert r.status_code == 200


def test_many_health_requests_no_rate_limit():
    """Many /health requests succeed when FABRIC_RATE_LIMIT is not set."""
    with _client() as client:
        for _ in range(10):
            r = client.get("/health")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Rate limiting enabled
# ---------------------------------------------------------------------------

def test_rate_limit_health_always_exempt():
    """/health is always exempt from rate limiting even when limit is 1."""
    with _client(rate_limit="1") as client:
        for _ in range(5):
            r = client.get("/health")
    assert r.status_code == 200


def test_rate_limit_within_window_passes():
    """Requests within the rate limit pass (auth → 401, not rate limited → 429)."""
    with _client(rate_limit="5") as client:
        # 5 requests are allowed; each returns 401 (auth, not rate limited)
        for _ in range(5):
            r = client.post("/run", json={"prompt": "hi"})
        assert r.status_code == 401  # auth rejected, NOT 429


def test_rate_limit_exceeded_returns_429():
    """Exceeding the rate limit returns 429 before auth runs."""
    with _client(rate_limit="2") as client:
        # Consume the 2 allowed slots (auth rejects with 401)
        client.post("/run", json={"prompt": "hi"})
        client.post("/run", json={"prompt": "hi"})
        # 3rd request hits the rate limit before auth
        r = client.post("/run", json={"prompt": "hi"})
    assert r.status_code == 429


def test_rate_limit_429_has_retry_after_header():
    """429 response includes a Retry-After header."""
    with _client(rate_limit="1") as client:
        client.post("/run", json={"prompt": "hi"})  # consume the 1 slot
        r = client.post("/run", json={"prompt": "hi"})
    assert r.status_code == 429
    assert "Retry-After" in r.headers
    assert int(r.headers["Retry-After"]) > 0


def test_rate_limit_429_json_body():
    """429 response body contains error and detail keys."""
    with _client(rate_limit="1") as client:
        client.post("/run", json={"prompt": "hi"})
        r = client.post("/run", json={"prompt": "hi"})
    assert r.status_code == 429
    body = r.json()
    assert body["error"] == "Too Many Requests"
    assert "detail" in body


def test_rate_limit_stream_endpoint_also_rate_limited():
    """POST /run/stream is also subject to rate limiting."""
    with _client(rate_limit="1") as client:
        client.post("/run/stream", json={"prompt": "hi"})
        r = client.post("/run/stream", json={"prompt": "hi"})
    assert r.status_code == 429


def test_rate_limit_invalid_value_passes_through():
    """Non-integer FABRIC_RATE_LIMIT is ignored (middleware disabled)."""
    with _client(rate_limit="not-a-number") as client:
        # All requests fall through to auth (401), no 429
        for _ in range(5):
            r = client.post("/run", json={"prompt": "hi"})
    assert r.status_code == 401  # auth, not rate limit


def test_rate_limit_zero_passes_through():
    """FABRIC_RATE_LIMIT=0 is treated as disabled."""
    with _client(rate_limit="0") as client:
        for _ in range(5):
            r = client.post("/run", json={"prompt": "hi"})
    assert r.status_code == 401  # auth, not rate limit
