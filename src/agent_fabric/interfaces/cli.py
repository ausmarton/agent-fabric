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
from agent_fabric.infrastructure.chat import build_chat_client
from agent_fabric.infrastructure.llm_discovery import resolve_llm
from agent_fabric.infrastructure.telemetry import setup_telemetry
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
    setup_telemetry(config)
    try:
        resolved = resolve_llm(config, model_key)
    except RuntimeError as e:
        rprint(f"[red]{e}[/red]")
        sys.exit(1)

    rprint(f"[dim]Using model: {resolved.model} at {resolved.base_url}[/dim]")
    rprint("[dim]Running task...[/dim]")

    chat_client = build_chat_client(resolved.model_config)
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


# ---------------------------------------------------------------------------
# fabric logs subcommands
# ---------------------------------------------------------------------------

logs_app = typer.Typer(help="Inspect past runs.")
app.add_typer(logs_app, name="logs")


@logs_app.command("list")
def logs_list(
    workspace: str = typer.Option(
        ".fabric", "--workspace", "-w", help="Workspace root (default: .fabric)."
    ),
    limit: int = typer.Option(20, "--limit", "-n", help="Maximum number of runs to show."),
) -> None:
    """List recent runs (most recent first)."""
    import datetime
    from agent_fabric.infrastructure.workspace.run_reader import list_runs

    summaries = list_runs(workspace, limit=limit)
    if not summaries:
        rprint(f"[dim]No runs found in {workspace}/runs/[/dim]")
        return

    from rich.table import Table
    table = Table(title=f"Recent runs ({workspace})", show_header=True, header_style="bold")
    table.add_column("Run ID", style="cyan", no_wrap=True)
    table.add_column("Started", style="dim")
    table.add_column("Specialists", style="green")
    table.add_column("Events", justify="right")
    table.add_column("Summary", overflow="fold")

    for s in summaries:
        started = (
            datetime.datetime.fromtimestamp(s.first_event_ts).strftime("%Y-%m-%d %H:%M:%S")
            if s.first_event_ts is not None
            else "—"
        )
        specialists = ", ".join(s.specialist_ids) if s.specialist_ids else (s.specialist_id or "—")
        summary = (s.payload_summary or "")[:80]
        table.add_row(s.run_id, started, specialists, str(s.event_count), summary)

    from rich.console import Console
    Console().print(table)


@logs_app.command("show")
def logs_show(
    run_id: str = typer.Argument(..., help="Run ID to inspect."),
    workspace: str = typer.Option(
        ".fabric", "--workspace", "-w", help="Workspace root (default: .fabric)."
    ),
    kinds: str = typer.Option(
        "", "--kinds", "-k",
        help="Comma-separated list of event kinds to show (e.g. 'llm_request,tool_call'). Shows all if empty.",
    ),
) -> None:
    """Show the runlog for a specific run (pretty-printed JSON)."""
    from agent_fabric.infrastructure.workspace.run_reader import read_run_events
    from rich.syntax import Syntax
    from rich.console import Console

    try:
        events = read_run_events(run_id, workspace)
    except FileNotFoundError as e:
        rprint(f"[red]{e}[/red]")
        sys.exit(1)

    filter_kinds = {k.strip() for k in kinds.split(",") if k.strip()} if kinds else None
    shown = [e for e in events if filter_kinds is None or e.get("kind") in filter_kinds]

    console = Console()
    rprint(f"[bold]Run:[/bold] {run_id}  [dim]({len(shown)}/{len(events)} events)[/dim]")
    for ev in shown:
        console.print(Syntax(json.dumps(ev, indent=2, ensure_ascii=False), "json", theme="monokai"))
