# Contributing to agent-fabric

Thank you for your interest in contributing. This document covers setting up your development environment, running tests, code style, and how to add new capabilities.

---

## Table of contents

1. [Development setup](#development-setup)
2. [Running tests](#running-tests)
3. [Code style](#code-style)
4. [Project structure](#project-structure)
5. [Adding a new specialist pack](#adding-a-new-specialist-pack)
6. [Adding a new tool](#adding-a-new-tool)
7. [Adding a new LLM backend](#adding-a-new-llm-backend)
8. [Architecture decisions](#architecture-decisions)
9. [Submitting changes](#submitting-changes)

---

## Development setup

```bash
# Clone the repo
git clone <repo-url>
cd agent-fabric

# Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install with dev dependencies (includes mcp, pytest, pytest-asyncio)
pip install -e ".[dev]"

# Optional: OpenTelemetry traces
pip install -e ".[otel]"
```

The `[dev]` extra installs everything needed for tests and the MCP subsystem. No Ollama is required to run the fast test suite (see below).

---

## Running tests

### Fast CI (no LLM required)

```bash
pytest tests/ -k "not real_llm and not real_mcp and not podman" -q
```

This runs the full suite of unit and integration tests using mocked LLM clients — no external services needed. **Target: 368 pass.** This is the check to run before and after every change.

### Test markers

| Marker | Requirement | How to run |
|---|---|---|
| *(none)* | None | `pytest tests/ -q` (fast subset included automatically) |
| `real_llm` | Live Ollama + a pulled model | `pytest tests/ -m real_llm` |
| `real_mcp` | `npx` + a published MCP server package | `pytest tests/ -m real_mcp` |
| `podman` | Podman + a pulled container image | `pytest tests/ -m podman` |

### Full validation (real LLM required)

```bash
python scripts/validate_full.py
```

Ensures Ollama is reachable (starts it if `local_llm_ensure_available: true`), then runs **all** tests including the real-LLM E2E tests. Use this to validate integration end-to-end.

### Single E2E smoke test

```bash
python scripts/verify_working_real.py
```

Runs one engineering task, asserts `tool_call`/`tool_result` events exist, and checks workspace artifacts.

---

## Code style

We use [ruff](https://docs.astral.sh/ruff/) with line length 100.

```bash
ruff check src/ tests/
```

Key conventions:
- **No `from __future__` magic beyond `annotations`** — already used where needed.
- **No bare `except Exception`** in tool execution paths — catch specific exception types (see `execute_task.py` for the pattern).
- **No `print()`** in library code — use `logging.getLogger(__name__)`.
- **Async tool execution**: `execute_tool()` is `async def`; sync tool functions can be called directly (no `run_in_executor` needed).
- **Ports, not concrete types**: application-layer code (`execute_task.py`, `recruit.py`) imports only from `domain` and `application.ports` — never from `infrastructure`. This is enforced by the layer dependency rule (see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) §7).

---

## Project structure

```
src/agent_fabric/
├── domain/         Pure data structures (Task, RunResult, LLMResponse, …). No I/O.
├── application/    Business logic (execute_task, recruit). Imports domain + ports only.
├── infrastructure/ Adapters: LLM clients, specialist packs, tools, workspace, MCP.
├── interfaces/     Entry points: CLI (Typer) + HTTP API (FastAPI).
└── config/         Pydantic schema, load_config(), capabilities.

tests/              Mirrors src layout. Unit tests use mocked ports; no real LLM needed.
examples/           Sample config files.
scripts/            Validation and verification helpers.
docs/               Architecture, decisions, vision, plan, backlog.
```

The architecture follows the **hexagonal (ports-and-adapters) pattern** strictly:

```
interfaces → application (ports) ← infrastructure
                    ↑
                  domain
```

`execute_task.py` and `recruit.py` are the core use cases. They never import from `infrastructure` — they receive everything via protocol injection. This keeps them testable with mocked ports and independent of any backend.

---

## Adding a new specialist pack

### Option A — config-driven (recommended, no core change)

Write a factory function that returns a `SpecialistPack`:

```python
# mypackage/packs.py
from agent_fabric.infrastructure.specialists.base import BaseSpecialistPack
from agent_fabric.infrastructure.specialists.tool_defs import make_tool_def, make_finish_tool_def

def build_my_pack(workspace_path: str, network_allowed: bool) -> BaseSpecialistPack:
    async def my_tool(args: dict) -> dict:
        return {"result": args.get("input", "")}

    return BaseSpecialistPack(
        specialist_id="my_specialist",
        system_prompt="You are a ... specialist. Use my_tool to ...",
        tool_map={"my_tool": my_tool},
        tool_definitions=[
            make_tool_def(
                "my_tool",
                "Does something useful.",
                {
                    "type": "object",
                    "properties": {"input": {"type": "string", "description": "Input text"}},
                    "required": ["input"],
                },
            ),
            make_finish_tool_def(),
        ],
        workspace_path=workspace_path,
    )
```

Register in your config:

```json
{
  "specialists": {
    "my_specialist": {
      "description": "Does useful things.",
      "workflow":    "my_specialist",
      "builder":     "mypackage.packs:build_my_pack",
      "capabilities": ["my_capability"]
    }
  }
}
```

The registry imports and calls `build_my_pack(workspace_path, network_allowed)` at `get_pack()` time. No changes to core code.

### Option B — built-in pack

1. Add `src/agent_fabric/infrastructure/specialists/my_pack.py` with `build_my_pack(workspace_path, network_allowed)`.
2. Register in `_DEFAULT_BUILDERS` in `infrastructure/specialists/registry.py`.
3. Add an entry to `DEFAULT_CONFIG` in `config/schema.py` and add its capability keywords to `config/capabilities.py`.
4. Write tests in `tests/test_packs.py` or a new `tests/test_my_pack.py`.

### Adding MCP tools to a pack (no Python needed)

```json
"specialists": {
  "my_specialist": {
    "mcp_servers": [
      {
        "name": "my_server",
        "transport": "stdio",
        "command": "npx",
        "args": ["--yes", "--", "@my-org/mcp-server"],
        "env": {"API_TOKEN": "${MY_TOKEN}"}
      }
    ]
  }
}
```

MCP tools are auto-discovered at startup and appear as `mcp__my_server__<tool_name>` in the LLM's tool list. See [docs/MCP_INTEGRATIONS.md](docs/MCP_INTEGRATIONS.md) for worked examples.

---

## Adding a new tool

1. Add a function in `infrastructure/tools/` that accepts a `SandboxPolicy` (if needed) and returns `dict`.
2. Register it in the relevant pack factory using `make_tool_def(name, description, parameters_schema)`.
3. If the tool has security implications (external network, filesystem), add it to the appropriate gate (`network_allowed` check, `SandboxPolicy.safe_path()` for paths).
4. Write unit tests with a mocked sandbox.

Example of a sandboxed file tool:

```python
from agent_fabric.infrastructure.tools.sandbox import SandboxPolicy

def read_text(args: dict, sandbox: SandboxPolicy) -> dict:
    path = sandbox.safe_path(args["path"])   # raises PermissionError if path escapes workspace
    try:
        return {"content": path.read_text(encoding="utf-8")}
    except OSError as exc:
        return {"error": str(exc)}
```

---

## Adding a new LLM backend

Implement the `ChatClient` protocol from `application/ports.py`:

```python
from agent_fabric.application.ports import ChatClient
from agent_fabric.domain.models import LLMResponse

class MyBackendClient:
    async def chat(
        self,
        messages: list[dict],
        model: str,
        *,
        tools: list[dict] | None = None,
        temperature: float,
        top_p: float,
        max_tokens: int,
    ) -> LLMResponse:
        ...
```

Wire it into `infrastructure/chat/__init__.py`'s `build_chat_client()` factory by adding a new `backend` value to `ModelConfig`. No changes to `execute_task` or any other layer.

---

## Architecture decisions

Before making a significant design change, read [docs/DECISIONS.md](docs/DECISIONS.md). It contains 11 Architecture Decision Records (ADRs) that explain the rationale behind key choices. If you propose a change that touches settled design (e.g. switching from native tool calling to JSON-in-content, removing the `finish_task` gate), open a discussion and record a new ADR.

The principles from [docs/VISION.md](docs/VISION.md) are non-negotiable:
- **Quality over speed**: correct output matters more than fast output.
- **Local-first**: local LLM is the default. Cloud is an opt-in quality fallback, not a connection fallback.
- **Portable and clean**: hexagonal architecture, no hardcoded infrastructure in the application layer.

---

## Submitting changes

1. **Branch** off `main` with a descriptive name (`feat/parallel-task-forces`, `fix/routing-fallback`).
2. **Run the fast CI** before and after your change: `pytest tests/ -k "not real_llm and not real_mcp and not podman" -q`.
3. **Add tests** for any new behaviour. The fast CI should cover new code without requiring a real LLM.
4. **Update docs** if your change affects user-visible behaviour, architecture, or configuration:
   - User-facing: update `README.md` (CLI, HTTP API, config sections as relevant).
   - Architecture: update `docs/ARCHITECTURE.md` (component map, data flow, runlog events).
   - Decisions: add an ADR to `docs/DECISIONS.md` for significant design choices.
   - Phase tracking: tick off deliverables in `docs/BACKLOG.md`; update `docs/STATE.md`.
5. **Open a pull request** with a clear description of what changed and why.
