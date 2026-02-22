"""OpenAI-compatible HTTP chat client (default config points at Ollama)."""

from __future__ import annotations

from typing import Any, Dict, List

import httpx


class OllamaChatClient:
    """OpenAI-compatible HTTP client: POST /chat/completions with model, messages, temperature, top_p, max_tokens. Default config points at Ollama; works with any server exposing the same API."""

    def __init__(self, base_url: str, api_key: str = "", timeout_s: float = 120.0):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout_s

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        temperature: float = 0.1,
        top_p: float = 0.9,
        max_tokens: int = 2048,
    ) -> str:
        url = f"{self._base_url}/chat/completions"
        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        # OpenAI compat: model + messages required. stream=false for single JSON response.
        # Some backends (e.g. Ollama) can 400 on extra top-level params; use only widely supported ones.
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
        }
        # Use explicit read timeout so large models have time to respond
        timeout = httpx.Timeout(self._timeout)
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(url, headers=headers, json=payload)
            if r.status_code == 400:
                # Ollama and some others 400 on unknown params; retry with minimal payload
                payload_minimal: Dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "stream": False,
                }
                r2 = await client.post(url, headers=headers, json=payload_minimal)
                r2.raise_for_status()
                data = r2.json()
            else:
                r.raise_for_status()
                data = r.json()
        return data["choices"][0]["message"]["content"]
