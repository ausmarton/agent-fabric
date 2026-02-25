# agent-fabric

A **quality-first agent orchestration framework** for local LLM inference.

- **Router + Supervisor** decomposes tasks into capabilities, recruits the right specialist packs, and runs them.
- **Specialist packs** are modular and composable: engineering, research, enterprise research — or add your own.
- **Local-first**: Ollama is the default and primary backend; any OpenAI-compatible server works via config.
- **Extensible via MCP**: connect GitHub, Confluence, Jira, filesystem, and other tool servers with a single config entry — no custom Python required.
- **Observable**: structured runlogs, persistent cross-run index, real-time SSE streaming, OpenTelemetry traces.

---

## Key features

| Feature | Details |
|---|---|
| **Specialist packs** | Engineering (shell, file I/O, test, deploy-propose-only), Research (web search, fetch, citations), Enterprise Research (GitHub/Confluence/Jira via MCP, cross-run memory search) |
| **Task decomposition** | Prompt → capability IDs → recruit the right pack(s) automatically |
| **Task forces** | Multiple packs run sequentially (with context handoff) or in parallel (`asyncio.gather`) for a single task |
| **MCP tool servers** | stdio or SSE MCP servers attached per specialist via config; tools merged transparently |
| **Cloud fallback** | Local model tried first; cloud model used when local fails a quality bar (no tool calls, malformed args) |
| **Podman isolation** | Optional: wrap any pack with `ContainerisedSpecialistPack` by setting `container_image` in config |
| **Semantic run index** | Every run is indexed; past runs are searchable by keyword or embedding similarity (`fabric logs search`) |
| **Real-time streaming** | `POST /run/stream` streams all run events as Server-Sent Events |
| **Run status** | `GET /runs/{run_id}/status` returns `running` / `completed` without reading the full runlog |
| **OpenTelemetry** | Optional `[otel]` dep; `fabric.execute_task`, `fabric.llm_call`, `fabric.tool_call` spans |

---

## Installation

### From PyPI (recommended)

```bash
pip install agent-fabric
```

Install optional extras:

```bash
pip install "agent-fabric[otel]"   # OpenTelemetry tracing
pip install "agent-fabric[mcp]"    # MCP tool server support
```

### Docker (batteries-included: Ollama + agent-fabric)

```bash
# Clone the repo for the config and docker-compose file
git clone https://github.com/ausmarton/agent-fabric.git
cd agent-fabric

# Start Ollama + agent-fabric (pulls qwen2.5:7b on first run)
docker compose up -d

# Run a task
curl -X POST http://localhost:8080/run \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Create a file hello.txt with content Hello World", "pack": "engineering"}'
```

The `docker-compose.yml` includes an Ollama service with a health check, an agent-fabric service, and a one-shot `model-pull` service that exits after pulling `qwen2.5:7b`.

To use a different model, edit `examples/ollama.json` and re-mount it via `FABRIC_CONFIG_PATH`.

### From source

```bash
git clone https://github.com/ausmarton/agent-fabric.git
cd agent-fabric
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

---

## Quick start (local Ollama)

### 1. System dependencies

```bash
sudo dnf install -y python3 python3-devel gcc gcc-c++ make cmake git ripgrep jq
```

### 2. Install and start Ollama

```bash
# Install (pick one)
curl -fsSL https://ollama.com/install.sh | sh          # official script
# OR: sudo dnf install -y ollama                       # Fedora package

# Start (if not already running as a service)
ollama serve
```

Pull a model (agent-fabric auto-pulls `qwen2.5:7b` if no chat model is found, but pre-pulling is faster):

```bash
ollama pull qwen2.5:7b     # fast model (default)
ollama pull qwen2.5:14b    # quality model (optional)
```

Any other model works — set `FABRIC_CONFIG_PATH` to point at a config with your preferred model name.

### 3. Install agent-fabric

```bash
pip install agent-fabric
# or from source:
# cd /path/to/agent-fabric && pip install -e .
```

### 4. Run

```bash
# Quick smoke test — creates a file and lists the workspace
fabric run "Create a file hello.txt with content Hello World, then list the workspace." --pack engineering
```

You should see a run directory path and JSON with `"action": "final"`. Check:
- `.fabric/runs/<run_id>/workspace/hello.txt` — artifact
- `.fabric/runs/<run_id>/runlog.jsonl` — structured event log (tool calls, LLM responses, etc.)

---

## CLI reference

```
fabric run PROMPT [OPTIONS]

  Run a task using a specialist pack.

  Options:
    --pack TEXT              Specialist ID (e.g. engineering, research).
                             Omit to let the router pick based on capabilities.
    --model-key TEXT         Which model entry to use from config [default: quality]
    --network-allowed / --no-network-allowed
                             Allow web tools (web_search, fetch_url) [default: enabled]
    --verbose                Enable DEBUG logging

fabric serve [OPTIONS]

  Start the HTTP API server.

  Options:
    --host TEXT  [default: 127.0.0.1]
    --port INT   [default: 8787]

fabric logs list [OPTIONS]

  List past runs (most recent first).

  Options:
    --workspace PATH   [default: .fabric]
    --limit N          [default: 20]

fabric logs show RUN_ID [OPTIONS]

  Pretty-print runlog events for a run.

  Options:
    --workspace PATH
    --kinds TEXT   Comma-separated event kinds to filter
                   (e.g. tool_call,tool_result)

fabric logs search QUERY [OPTIONS]

  Search the cross-run index.
  Uses semantic similarity when embedding_model is configured;
  falls back to keyword/substring matching otherwise.

  Options:
    --workspace PATH
    --limit N          [default: 10]
```

---

## HTTP API

Start the server:

```bash
fabric serve
# or: uvicorn agent_fabric.interfaces.http_api:app --host 0.0.0.0 --port 8787
```

### `GET /health`

```json
{"ok": true}
```

### `POST /run` — blocking run

```bash
curl -X POST http://127.0.0.1:8787/run \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Create ok.txt with content OK", "pack": "engineering"}'
```

Request body:

```json
{
  "prompt": "your task",
  "pack": "engineering",       // optional; omit to auto-route
  "model_key": "quality",      // optional; default "quality"
  "network_allowed": true      // optional; default true
}
```

Response: the `finish_task` payload merged with a `_meta` field containing `run_id`, `specialist_ids`, `workspace`, `model`, etc.

### `POST /run/stream` — Server-Sent Events

Streams run events in real-time as they happen:

```bash
curl -N -X POST http://127.0.0.1:8787/run/stream \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Create ok.txt with content OK", "pack": "engineering"}'
```

Each event is a `data: <json>\n\n` SSE line. Event kinds:

| Kind | When |
|---|---|
| `recruitment` | Specialist(s) selected |
| `llm_request` | Before each LLM call |
| `llm_response` | After each LLM call |
| `tool_call` | Before each tool execution |
| `tool_result` | Successful tool result |
| `tool_error` | Tool raised an exception |
| `security_event` | Sandbox violation (path escape, disallowed command) |
| `cloud_fallback` | Local model fell back to cloud |
| `pack_start` | A specialist pack started (task forces) |
| `run_complete` | Run finished successfully |
| `_run_done_` | Terminal sentinel — stream ends |
| `_run_error_` | Terminal sentinel — run failed |

### API key authentication

When `FABRIC_API_KEY` is set, every endpoint except `GET /health` requires an `Authorization: Bearer <key>` header:

```bash
export FABRIC_API_KEY="your-strong-secret"
fabric serve

# Include the header in every request:
curl -X POST http://127.0.0.1:8787/run \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-strong-secret" \
  -d '{"prompt": "hello"}'
```

Leave `FABRIC_API_KEY` unset (default) to disable authentication — suitable for local use. Uses constant-time comparison (`hmac.compare_digest`) to prevent timing attacks.

### `GET /runs/{run_id}/status`

```bash
curl http://127.0.0.1:8787/runs/abc123.../status
```

```json
{"status": "completed", "run_id": "abc123...", "specialist_ids": ["engineering"], "task_force_mode": "sequential"}
```

Status values: `running`, `completed`. Returns HTTP 404 if the run ID is not found.

---

## Configuration

Set `FABRIC_CONFIG_PATH` to a JSON or YAML file to override the defaults.

```bash
export FABRIC_CONFIG_PATH=/path/to/your/config.json
```

The default config uses Ollama at `localhost:11434` with `qwen2.5:7b` (fast) and `qwen2.5:14b` (quality). Copy `examples/ollama.json` as a starting point.

### Key config fields

```json
{
  "models": {
    "fast":    {"base_url": "http://localhost:11434/v1", "model": "qwen2.5:7b",  "temperature": 0.1, "max_tokens": 1200},
    "quality": {"base_url": "http://localhost:11434/v1", "model": "qwen2.5:14b", "temperature": 0.1, "max_tokens": 2400}
  },
  "specialists": {
    "engineering": {
      "description": "Plan → implement → test → review → iterate.",
      "keywords":    ["build", "implement", "code", "python"],
      "workflow":    "engineering",
      "capabilities": ["code_execution", "file_io", "software_testing"]
    }
  },

  "routing_model_key": "fast",         // model used for LLM-based routing
  "task_force_mode": "sequential",     // "sequential" (default) or "parallel"

  "local_llm_ensure_available": true,  // start Ollama if unreachable
  "local_llm_start_cmd": ["ollama", "serve"],
  "auto_pull_if_missing": true,        // pull qwen2.5:7b when no model exists
  "auto_pull_model": "qwen2.5:7b",

  "run_index": {
    "embedding_model": "nomic-embed-text"   // enables semantic search; omit for keyword-only
  },

  "cloud_fallback": {
    "model_key": "cloud_quality",           // must exist in "models"
    "policy": "no_tool_calls"               // trigger: "no_tool_calls" | "malformed_args" | "always"
  },

  "telemetry": {
    "enabled": true,
    "exporter": "otlp",
    "otlp_endpoint": "http://localhost:4317"
  }
}
```

### Using a non-Ollama backend

Any OpenAI-compatible endpoint works. Set `backend: "generic"` for cloud/vLLM/LiteLLM servers (skips Ollama-specific 400 retry logic):

```json
"models": {
  "quality": {
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-4o",
    "api_key": "sk-...",
    "backend": "generic"
  }
}
```

Set `local_llm_ensure_available: false` when you manage the server yourself (CI, cloud deployments, etc.).

### MCP tool servers

Attach any MCP server to a specialist pack — no Python code required:

```json
"specialists": {
  "engineering": {
    "description": "Engineering with GitHub access.",
    "workflow": "engineering",
    "capabilities": ["code_execution", "file_io", "github_search"],
    "mcp_servers": [
      {
        "name": "github",
        "transport": "stdio",
        "command": "npx",
        "args": ["--yes", "--", "@modelcontextprotocol/server-github"],
        "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"}
      }
    ]
  }
}
```

Tools are auto-discovered at startup and prefixed `mcp__github__<tool>`. See [docs/MCP_INTEGRATIONS.md](docs/MCP_INTEGRATIONS.md) for GitHub, Confluence, Jira, and filesystem examples.

### Parallel task forces

Run multiple specialists concurrently for independent sub-tasks:

```json
"task_force_mode": "parallel"
```

In `sequential` mode (default) each pack receives the previous pack's output as context. In `parallel` mode all packs run concurrently via `asyncio.gather` and results are merged.

### Podman container isolation

```json
"specialists": {
  "engineering": {
    "container_image": "python:3.12-slim"
  }
}
```

All `shell` tool calls execute inside an isolated Podman container with the workspace mounted at `/workspace`. Requires Podman installed and the image available locally.

---

## Specialist packs

### Built-in packs

| ID | Description | Tools |
|---|---|---|
| `engineering` | Plan → implement → test → review | `shell`, `read_file`, `write_file`, `list_files`, `finish_task` |
| `research` | Scope → search → screen → extract → synthesize | `web_search`*, `fetch_url`*, `read_file`, `write_file`, `list_files`, `finish_task` |
| `enterprise_research` | GitHub/Confluence/Jira search + cross-run memory | All research tools + `cross_run_search` + any configured MCP tools |

`*` Requires `network_allowed: true` (default).

### Adding a custom pack

**Option A — config-driven (no core change required):**

```python
# mypackage/packs.py
from agent_fabric.infrastructure.specialists.base import BaseSpecialistPack
from agent_fabric.infrastructure.specialists.tool_defs import make_tool_def, make_finish_tool_def

def build_my_pack(workspace_path: str, network_allowed: bool):
    tools = {
        "my_tool": lambda args: {"result": "..."},
    }
    tool_definitions = [
        make_tool_def("my_tool", "Does something useful.", {"type": "object", "properties": {...}, "required": [...]}),
        make_finish_tool_def(),
    ]
    return BaseSpecialistPack(
        specialist_id="my_specialist",
        system_prompt="You are a ...",
        tool_map=tools,
        tool_definitions=tool_definitions,
        workspace_path=workspace_path,
    )
```

```json
"specialists": {
  "my_specialist": {
    "description": "My custom specialist.",
    "workflow":    "my_specialist",
    "builder":     "mypackage.packs:build_my_pack",
    "capabilities": ["my_capability"]
  }
}
```

**Option B — built-in:** add your pack factory to `infrastructure/specialists/`, register in `_DEFAULT_BUILDERS` in `registry.py`, and add an entry to `DEFAULT_CONFIG`. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) §5 for the full extension guide.

---

## Runlog

Every run produces `.fabric/runs/<run_id>/runlog.jsonl`. Each line:

```json
{"ts": 1708800000.123, "kind": "tool_call", "step": "step_0", "payload": {"tool": "shell", "args": {"cmd": "ls"}}}
```

Inspect with:

```bash
fabric logs show <run_id>
fabric logs show <run_id> --kinds tool_call,tool_result
```

---

## Testing

**Fast CI** (no LLM required, ~45 seconds, 370+ tests):

```bash
pip install -e ".[dev]"
pytest tests/ -k "not real_llm and not real_mcp and not podman" -q
```

**Full validation** (requires Ollama + a pulled model):

```bash
python scripts/validate_full.py
```

Ensures the LLM is reachable (starts it if needed via config), then runs all tests including real-LLM E2E tests. Use `ollama pull qwen2.5:7b` or set `FABRIC_CONFIG_PATH` to a config with a model you have.

**Single E2E check**:

```bash
python scripts/verify_working_real.py
```

Runs one engineering task end-to-end and asserts that `tool_call`/`tool_result` events exist and workspace artifacts are created.

**Test markers:**

| Marker | Meaning |
|---|---|
| `real_llm` | Requires a live Ollama instance |
| `real_mcp` | Requires `npx` and an MCP server package |
| `podman` | Requires Podman and a pulled container image |

---

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full contributor guide.

```bash
# Install dev dependencies (includes mcp, pytest, pytest-asyncio)
pip install -e ".[dev]"

# Optional: OpenTelemetry
pip install -e ".[otel]"

# Run fast tests
pytest tests/ -k "not real_llm and not real_mcp and not podman" -q

# Lint
ruff check src/ tests/
```

---

## Documentation

| Document | Purpose |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Layer design, component map, data flow, extension points |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Architecture Decision Records (ADR-001 to ADR-011) |
| [docs/VISION.md](docs/VISION.md) | Long-term vision, principles, use cases |
| [docs/PLAN.md](docs/PLAN.md) | Phases 1–8: deliverables and verification gates |
| [docs/STATE.md](docs/STATE.md) | Current phase, CI status, resumability guide |
| [docs/BACKLOG.md](docs/BACKLOG.md) | Prioritised work items; what to do next |
| [docs/CAPABILITIES.md](docs/CAPABILITIES.md) | Capability model and routing rules |
| [docs/MCP_INTEGRATIONS.md](docs/MCP_INTEGRATIONS.md) | MCP server setup (GitHub, Confluence, Jira, filesystem) |
| [docs/BACKENDS.md](docs/BACKENDS.md) | Using backends other than Ollama |
| [REQUIREMENTS.md](REQUIREMENTS.md) | MVP functional requirements and validation |

---

## License

[MIT](LICENSE)
