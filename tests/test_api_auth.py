"""Tests for optional API key authentication middleware.

The middleware is active only when the FABRIC_API_KEY environment variable is
set.  When inactive (no key), all requests pass through unchanged.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@contextmanager
def _app_client(api_key: str | None = None):
    """Return a TestClient with FABRIC_API_KEY optionally set."""
    from agent_fabric.interfaces.http_api import app
    env_patch = {"FABRIC_API_KEY": api_key} if api_key else {}
    # Ensure the key is absent when not provided
    with patch.dict(os.environ, env_patch, clear=False):
        if not api_key:
            os.environ.pop("FABRIC_API_KEY", None)
        yield TestClient(app, raise_server_exceptions=False)


def _mock_run_result():
    from agent_fabric.domain import RunId, RunResult
    return RunResult(
        run_id=RunId("x"), run_dir="/tmp/x", workspace_path="/tmp/x/w",
        specialist_id="engineering", model_name="mock",
        payload={"action": "final", "summary": "ok", "artifacts": [], "next_steps": [], "notes": ""},
    )


# ---------------------------------------------------------------------------
# Auth disabled (no FABRIC_API_KEY)
# ---------------------------------------------------------------------------

def test_health_accessible_without_key():
    """/health is accessible with no API key configured."""
    with _app_client() as client:
        r = client.get("/health")
    assert r.status_code == 200


def test_run_accessible_without_key():
    """POST /run is accessible with no API key configured (auth disabled)."""
    mock_result = _mock_run_result()
    mock_resolved = MagicMock(model_config=MagicMock(), base_url="http://localhost:11434/v1")
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("FABRIC_API_KEY", None)
        from agent_fabric.interfaces.http_api import app
        with patch("agent_fabric.interfaces.http_api.load_config"), \
             patch("agent_fabric.interfaces.http_api.resolve_llm", return_value=mock_resolved), \
             patch("agent_fabric.interfaces.http_api.build_chat_client"), \
             patch("agent_fabric.interfaces.http_api.execute_task", new_callable=AsyncMock, return_value=mock_result):
            client = TestClient(app, raise_server_exceptions=False)
            r = client.post("/run", json={"prompt": "hello"})
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Auth enabled (FABRIC_API_KEY set)
# ---------------------------------------------------------------------------

def test_health_exempt_from_auth():
    """/health is always accessible even when FABRIC_API_KEY is set."""
    with patch.dict(os.environ, {"FABRIC_API_KEY": "secret123"}):
        from agent_fabric.interfaces.http_api import app
        client = TestClient(app)
        r = client.get("/health")
    assert r.status_code == 200


def test_run_requires_auth_when_key_set():
    """POST /run with no Authorization header returns 401 when key is set."""
    with patch.dict(os.environ, {"FABRIC_API_KEY": "secret123"}):
        from agent_fabric.interfaces.http_api import app
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post("/run", json={"prompt": "hello"})
    assert r.status_code == 401
    assert "WWW-Authenticate" in r.headers
    assert r.headers["WWW-Authenticate"] == "Bearer"


def test_correct_key_passes():
    """POST /run with the correct Bearer token proceeds past auth."""
    mock_result = _mock_run_result()
    mock_resolved = MagicMock(model_config=MagicMock(), base_url="http://localhost:11434/v1")
    with patch.dict(os.environ, {"FABRIC_API_KEY": "secret123"}):
        from agent_fabric.interfaces.http_api import app
        with patch("agent_fabric.interfaces.http_api.load_config"), \
             patch("agent_fabric.interfaces.http_api.resolve_llm", return_value=mock_resolved), \
             patch("agent_fabric.interfaces.http_api.build_chat_client"), \
             patch("agent_fabric.interfaces.http_api.execute_task", new_callable=AsyncMock, return_value=mock_result):
            client = TestClient(app, raise_server_exceptions=False)
            r = client.post(
                "/run",
                json={"prompt": "hello"},
                headers={"Authorization": "Bearer secret123"},
            )
    assert r.status_code == 200


def test_wrong_key_rejected():
    """POST /run with a wrong Bearer token returns 401."""
    with patch.dict(os.environ, {"FABRIC_API_KEY": "secret123"}):
        from agent_fabric.interfaces.http_api import app
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post(
            "/run",
            json={"prompt": "hello"},
            headers={"Authorization": "Bearer wrongkey"},
        )
    assert r.status_code == 401
    assert r.json()["error"] == "Unauthorized"


def test_malformed_auth_header_rejected():
    """Authorization header without 'Bearer ' prefix returns 401."""
    with patch.dict(os.environ, {"FABRIC_API_KEY": "secret123"}):
        from agent_fabric.interfaces.http_api import app
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post(
            "/run",
            json={"prompt": "hello"},
            headers={"Authorization": "Token secret123"},
        )
    assert r.status_code == 401


def test_stream_endpoint_also_requires_auth():
    """POST /run/stream is also protected when FABRIC_API_KEY is set."""
    with patch.dict(os.environ, {"FABRIC_API_KEY": "secret123"}):
        from agent_fabric.interfaces.http_api import app
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post("/run/stream", json={"prompt": "hello"})
    assert r.status_code == 401


def test_status_endpoint_also_requires_auth():
    """GET /runs/{id}/status is also protected when FABRIC_API_KEY is set."""
    with patch.dict(os.environ, {"FABRIC_API_KEY": "secret123"}):
        from agent_fabric.interfaces.http_api import app
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/runs/some-run-id/status")
    assert r.status_code == 401
