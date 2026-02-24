"""CLI: Typer app wired to execute_task."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

import httpx
import typer
from rich import print as rprint
from rich.panel import Panel

from agent_fabric.application.execute_task import execute_task
from agent_fabric.config import load_config
from agent_fabric.domain import Task, build_task
from agent_fabric.infrastructure.llm_discovery import resolve_llm
from agent_fabric.infrastructure.ollama import OllamaChatClient
from agent_fabric.infrastructure.workspace import FileSystemRunRepository
from agent_fabric.infrastructure.specialists import ConfigSpecialistRegistry

app = typer.Typer(help="agent-fabric: on-demand specialist packs (Ollama by default).")


def _workspace_root() -> str:
    return os.environ.get("FABRIC_WORKSPACE", ".fabric")


@app.command()
def run(
    prompt: str = typer.Argument(..., help="What you want the fabric to do."),
    pack: str = typer.Option("", help="Force a pack (engineering|research). Leave empty for auto-routing."),
    model_key: str = typer.Option("quality", help="Which model profile to use (quality|fast)."),
    network_allowed: bool = typer.Option(True, help="Allow network tools (web_search, fetch_url)."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose (DEBUG) logging to stderr."),
) -> None:
    """Run a task end-to-end and print result + run directory."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    config = load_config()
    try:
        resolved = resolve_llm(config, model_key)
    except RuntimeError as e:
        rprint(f"[red]{e}[/red]")
        sys.exit(1)

    rprint(f"[dim]Using model: {resolved.model} at {resolved.base_url}[/dim]")
    rprint("[dim]Running task...[/dim]")

    chat_client = OllamaChatClient(
        base_url=resolved.base_url,
        api_key=resolved.model_config.api_key,
        timeout_s=resolved.model_config.timeout_s,
    )
    run_repository = FileSystemRunRepository(workspace_root=_workspace_root())
    specialist_registry = ConfigSpecialistRegistry(config)

    task = build_task(prompt, pack, model_key, network_allowed)
    try:
        result = asyncio.run(
            execute_task(
                task,
                chat_client=chat_client,
                run_repository=run_repository,
                specialist_registry=specialist_registry,
                config=config,
                resolved_model_cfg=resolved.model_config,
                max_steps=40,
            )
        )
    except httpx.ConnectError as e:
        rprint(
            f"[red]LLM server unreachable.[/red]\n"
            f"  URL: {resolved.base_url}\n  Error: {e}\n"
            "  Install/start your backend (e.g. Ollama: ollama serve) or set local_llm_ensure_available: false."
        )
        sys.exit(1)
    except httpx.ReadTimeout:
        rprint(
            f"[red]LLM read timeout.[/red] The model ({resolved.model}) took too long to respond.\n"
            f"  Use a smaller/faster model or increase timeout in config (models.*.timeout_s)."
        )
        sys.exit(1)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            rprint(
                f"[red]Model not found (404).[/red]\n"
                f"  URL: {resolved.base_url}\n  Model: {resolved.model}\n"
                f"  Pull with: [bold]ollama pull {resolved.model}[/bold] or set FABRIC_CONFIG_PATH."
            )
        elif e.response.status_code == 400:
            try:
                err_body = e.response.json()
                detail = (
                    err_body.get("error", {}).get("message")
                    if isinstance(err_body.get("error"), dict)
                    else err_body.get("message", str(err_body))
                )
            except Exception:
                detail = e.response.text or str(e)
            rprint(
                f"[red]LLM server returned 400 Bad Request.[/red]\n"
                f"  URL: {resolved.base_url}\n  Model: {resolved.model}\n  Detail: {detail}"
            )
        else:
            rprint(
                f"[red]LLM server error.[/red]\n"
                f"  URL: {resolved.base_url}\n  Status: {e.response.status_code}\n  {e}"
            )
        sys.exit(1)

    rprint(
        Panel.fit(
            f"[bold]Pack:[/bold] {result.specialist_id}\n"
            f"[bold]Run dir:[/bold] {result.run_dir}\n"
            f"[bold]Workspace:[/bold] {result.workspace_path}\n"
            f"[bold]Model:[/bold] {result.model_name}"
        )
    )
    rprint(json.dumps(result.payload, indent=2, ensure_ascii=False))


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8787) -> None:
    """Run the HTTP API (FastAPI + uvicorn)."""
    import uvicorn
    uvicorn.run("agent_fabric.interfaces.http_api:app", host=host, port=port, reload=False)
