"""
Ensure an LLM server is available: if the configured endpoint is unreachable,
optionally start it (e.g. local_llm_start_cmd) and wait until healthy.

Enables a self-contained fabric that can spin up its own LLM when configured.
The fabric does not stop a server it started; the process is left running so
subsequent runs can use it. Clean teardown: no temp files or stray state;
run artifacts live under workspace_root/runs/. To avoid starting a server,
set local_llm_ensure_available: false in config.
"""

from __future__ import annotations

import subprocess
import time
from typing import List

import httpx


def _health_url(base_url: str) -> str:
    """URL to probe for liveness. For base_url ending in /v1, probe server root (e.g. http://host:port/)."""
    from urllib.parse import urlparse
    p = urlparse(base_url)
    if p.path.rstrip("/").endswith("/v1"):
        # OpenAI-compat base; check server root (e.g. http://localhost:11434/)
        return f"{p.scheme}://{p.netloc}/"
    return base_url.rstrip("/") or base_url


def _check_reachable(base_url: str, timeout_s: float = 5.0) -> bool:
    """Return True if the LLM server at base_url responds."""
    try:
        url = _health_url(base_url)
        with httpx.Client(timeout=timeout_s) as client:
            r = client.get(url)
            return r.status_code < 500
    except Exception:
        return False


def ensure_llm_available(
    base_url: str,
    start_cmd: List[str] | None = None,
    timeout_s: int = 90,
    poll_interval_s: float = 1.5,
) -> bool:
    """
    Ensure the LLM at base_url is reachable. If not and start_cmd is set,
    run start_cmd in the background and poll until the server responds or timeout.

    Returns True if the server is (or becomes) reachable; raises TimeoutError
    if we started the process but the server did not become ready in time.
    """
    if _check_reachable(base_url):
        return True
    if not start_cmd:
        return False
    # Start the server process (detached so it outlives us)
    try:
        subprocess.Popen(
            start_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except FileNotFoundError:
        raise FileNotFoundError(
            f"Cannot start LLM server: command not found: {start_cmd[0]}. "
            "Install the backend (e.g. Ollama https://ollama.com) or set the full path to the executable."
        ) from None
    # Poll until reachable or timeout
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        time.sleep(poll_interval_s)
        if _check_reachable(base_url, timeout_s=3.0):
            return True
    raise TimeoutError(
        f"LLM server at {base_url} did not become ready within {timeout_s}s after running: {start_cmd}"
    )
