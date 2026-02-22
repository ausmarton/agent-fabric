# agent-fabric

A **quality-first** “agent fabric” for local inference:
- **Router + Supervisor** picks a specialist pack on demand
- Packs are modular (engineering, research), with explicit tool schemas
- **Uses Ollama** for local LLM inference by default; other OpenAI-compatible servers are supported via config.

- **Requirements and validation:** [REQUIREMENTS.md](REQUIREMENTS.md)  
- **Long-term vision:** [docs/VISION.md](docs/VISION.md)  
- **Build plan and current state:** [docs/PLAN.md](docs/PLAN.md), [docs/STATE.md](docs/STATE.md) — use these to resume work or see what’s next.  
- **Design assessment:** [docs/DESIGN_ASSESSMENT.md](docs/DESIGN_ASSESSMENT.md) — how well the implementation matches the vision; Ollama and re-think notes.

This is an MVP designed to scale into:
- an engineering “team” (plan → implement → test → review → iterate)
- a research team (systematic review with screening log + evidence table + citations)
- later: enterprise connectors (Confluence/Jira/GitHub/Rally) via MCP or custom tools

## Quickstart (Fedora)

We use **Ollama** for local inference. Follow these steps in order; each block is copy-pastable.

### 1) System deps
```bash
sudo dnf install -y python3 python3-devel gcc gcc-c++ make cmake git ripgrep jq
```

### 2) Install and run Ollama
Install Ollama (pick one):

**Option A – official script**
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

**Option B – Fedora package** (if available for your release)
```bash
sudo dnf install -y ollama
```

Start the server (if not already running as a user or system service):
```bash
ollama serve
```
Leave this running in a terminal, or run it in the background (`ollama serve &`). On some setups Ollama runs as a service and you can skip this.

The fabric **discovers** what’s available: it talks to Ollama (and optionally other OpenAI-compatible backends), lists models, and picks the best match. If **no models** are available, it can **auto-pull** a default (e.g. `qwen2.5:7b`) so one command works. To pre-pull manually (optional):
```bash
ollama pull qwen2.5:7b
```
Optional, for `--model-key quality`:
```bash
ollama pull qwen2.5:14b
```

If you prefer a different model (e.g. `llama3.1:8b`), pull it and point the fabric at a config that uses it: copy `examples/ollama.json`, set the `model` field under `fast` and `quality` to your model name, then `export FABRIC_CONFIG_PATH=/path/to/that/config.json`. You can disable auto-pull by setting `auto_pull_if_missing: false` in config.

### 3) Create a venv and install the fabric
```bash
cd /path/to/agent-fabric   # repo root
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

Default config uses `http://localhost:11434/v1` and models `qwen2.5:7b` / `qwen2.5:14b`. No extra config if you use those.

### 4) Run the fabric
**Prerequisite:** Ollama must be running (the fabric can start it via config). The fabric discovers available models (skips embedding-only ones like bge-m3) and auto-pulls a default if no chat model exists.

**If the run seems stuck:** discovery may have picked a very large model (e.g. 72B). Use a smaller model via config: `FABRIC_CONFIG_PATH=examples/ollama-fast-verify.json fabric run "..."` (that config uses `llama3.1:8b`). Or copy `examples/ollama.json`, set `models.quality.model` to a model you have (e.g. `llama3.1:8b`), and point `FABRIC_CONFIG_PATH` at it.

**Verify everything works:** `python scripts/verify_working_real.py` (requires Ollama and at least one chat model).

Quick smoke test (creates a file and lists the workspace; usually under a minute):
```bash
fabric run "Create a file hello.txt with content Hello World. Then list the workspace." --pack engineering
```
You should see a run dir path and JSON with `"action": "final"` and `"artifacts": ["hello.txt"]`. Check `.fabric/runs/<run_id>/workspace/` for `hello.txt` and `.fabric/runs/<run_id>/runlog.jsonl` for `tool_call` / `tool_result` events.

Longer examples (may take 2–5+ minutes each):
```bash
fabric run "Create a tiny FastAPI service with a /health route and unit tests. Make it runnable with uvicorn." --pack engineering
```
```bash
fabric run "Do a mini systematic review of post-quantum cryptography performance impacts in real-time systems." --pack research
```

Outputs:
- A run directory with `runlog.jsonl` (all model and tool steps)
- A per-run `workspace/` with generated artifacts

## Quality gates
The engineering workflow enforces:
- “don’t claim it works unless you ran tests/build”
- use tools frequently
- propose deploy/push steps but **don’t execute** (human approval required)

## Testing

Use the right technique for the job: mocked and unit tests give fast feedback and validate wiring and behaviour in isolation. For integration and "everything works together" we need at least a couple of E2E tests that run against a real LLM; those are essential to ensure the full stack is integrated and working as expected.

**Full validation (proves system works):**
```bash
pip install -e ".[dev]"
python scripts/validate_full.py
```
This ensures the LLM is reachable (and starts it via config if needed), then runs pytest so all 42 tests run and pass. If the LLM cannot be reached or started, the script exits with failure. With Ollama: run `ollama serve` and `ollama pull qwen2.5:7b` (or set FABRIC_CONFIG_PATH to a config with a model you have pulled).

**Fast CI:**
```bash
FABRIC_SKIP_REAL_LLM=1 pytest tests/ -v
```
Runs 38 tests and skips the 4 real-LLM E2E tests. Use for quick feedback on wiring and unit/integration behaviour; it does not replace running real-LLM E2E for integration assurance.

**Single E2E check (real LLM):**
```bash
python scripts/verify_working_real.py
```
Runs one engineering task against the configured LLM and asserts tool_call/tool_result and workspace artifacts. Exits with instructions if the LLM is not available.

## Extending packs
Add a new specialist: implement a pack in **`src/agent_fabric/infrastructure/specialists/`** (system prompt, tools, and register in **`registry.py`**); add an entry to config **specialists** (see `agent_fabric.config.schema` and `examples/ollama.json`). One tool loop in `agent_fabric.application.execute_task`; no per-pack workflow files.

## Using another backend (not locked to Ollama)

The fabric uses the **OpenAI chat-completions API** (`POST /v1/chat/completions`). Ollama is the default because it’s easy to run locally; any server that speaks that API works (llama.cpp, vLLM, LiteLLM, OpenAI, etc.). See [docs/BACKENDS.md](docs/BACKENDS.md) for why we’re not stuck with Ollama and how the code stays portable.

To use another server, point config at it:

```bash
export FABRIC_CONFIG_PATH="/path/to/your/config.json"
```

In that config set `base_url` (e.g. `http://localhost:8000/v1`) and `model` to the name your server expects. See `examples/ollama.json` for the shape; duplicate and change `models`. If you run the server yourself, set `local_llm_ensure_available: false` or provide your own `local_llm_start_cmd`.

## Possible future improvements

- Replace keyword routing with a small router model and JSON schema output.
- Add containerized on-demand workers (e.g. Podman) per specialist role.
- Add MCP tool servers for Confluence, Jira, GitHub (least-privilege, sandboxed).
- Add a persistent vector store for enterprise RAG (document metadata and staleness).
- Add observability export (e.g. OpenTelemetry traces).
