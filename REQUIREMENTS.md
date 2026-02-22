# agent-fabric: Requirements and Validation

This document defines the current MVP (Phase 1). The long-term vision—use cases, principles, phasing, and alignment with the repo—is in [docs/VISION.md](docs/VISION.md).

## Purpose

agent-fabric is a **quality-first agent fabric** for local inference, **built for Ollama**:

1. **Routes** user prompts to a specialist pack (engineering or research) via keyword-based routing, or uses an explicitly chosen pack.
2. **Runs** a workflow that drives an LLM with tools in a loop until the task is completed or a step limit is reached.
3. **Produces** a per-run directory with a structured runlog and a workspace of artifacts.

We **use Ollama** for local inference by default (default config points at localhost:11434 and Ollama model names). Local LLM is the **default and primary** path: the fabric ensures it's available (including starting it when unreachable) by default; opt out with `local_llm_ensure_available: false` if you manage the server yourself. Cloud is used only when local **capability or quality** is insufficient (future). Other OpenAI-compatible servers are supported via config override.

---

## Functional Requirements

### FR1: CLI and API

- **FR1.1** The CLI shall provide:
  - `fabric run PROMPT` to run a task (with optional `--pack`, `--model-key`, `--no-network-allowed`).
  - `fabric serve` to run the HTTP API.
- **FR1.2** The HTTP API shall expose:
  - `GET /health` returning `{"ok": true}`.
  - `POST /run` accepting `{ "prompt", "pack?", "model_key?", "network_allowed?" }` and returning the same result shape as the CLI.

### FR2: Routing and packs

- **FR2.1** If `--pack` is not specified, the router shall choose a pack from config using keyword scoring over the prompt (default fallback: engineering for code-ish prompts, else research).
- **FR2.2** Two built-in packs shall be supported:
  - **engineering**: tools = shell, read_file, write_file, list_files; workflow = plan → implement → test → review → iterate.
  - **research**: tools = web_search, fetch_url, write_file, read_file, list_files; workflow = scope → search → screen → extract → synthesize.

### FR3: Execution

- **FR3.1** Each run shall create a unique run directory under `workspace_root/runs/<run_id>` and a `workspace` subdirectory for artifacts.
- **FR3.2** All LLM requests/responses and tool calls/results shall be appended to `runlog.jsonl` in the run directory.
- **FR3.3** The LLM client shall call the configured base URL at `/chat/completions` with the configured model name and parameters (temperature, top_p, max_tokens).

### FR4: Configuration

- **FR4.1** Default configuration shall use **Ollama** (base_url http://localhost:11434/v1, models e.g. qwen2.5:7b / qwen2.5:14b) and define two model profiles (`fast`, `quality`) and the two packs with their workflows and keywords. The fabric shall **ensure the local LLM is available by default** (check reachability; if unreachable, start via `local_llm_start_cmd` and wait for readiness); config may set `local_llm_ensure_available: false` to opt out.
- **FR4.2** If `FABRIC_CONFIG_PATH` is set to a valid file path, that file (JSON) shall be loaded and used as the fabric config; otherwise defaults are used.

### FR5: Quality and safety

- **FR5.1** Engineering pack: the agent must not claim success without having run tests/build via tools; deploy/push steps must be proposed for human approval and not executed automatically.
- **FR5.2** Research pack: only URLs actually fetched via `fetch_url` may be cited; screening log and evidence table shall be maintained in the workspace.
- **FR5.3** When `network_allowed` is false, research pack shall not perform web search or URL fetch (tools shall return a clear “network disabled” response if invoked).

### FR6: Sandbox and tools

- **FR6.1** File tools (read_file, write_file, list_files) shall be scoped to the run’s workspace directory; paths must not escape the sandbox.
- **FR6.2** Shell commands shall be restricted to an allowlist (e.g. python, pytest, bash, git, pip, make, …) and run with cwd within the workspace.

---

## Validation

### Manual validation (no LLM required for basic checks)

1. **CLI help**
   - `fabric --help`, `fabric run --help`, `fabric serve --help` run without error.

2. **Routing**
   - With no server running, `fabric run "build a small API"` shall create a run dir under `.fabric/runs/` and fail at the first LLM call (connection error). The chosen pack in logs/metadata should be engineering.
   - `fabric run "systematic review of X" --pack research` shall use research pack and fail at first LLM call; run dir and runlog.jsonl shall exist.

3. **Run output structure**
   - After any run (even failed), the run directory shall contain:
     - `runlog.jsonl` (at least one `llm_request` event once the workflow starts).
     - `workspace/` directory.

4. **API**
   - `fabric serve` and `curl http://127.0.0.1:8787/health` shall return `{"ok": true}`.

### End-to-end validation (real LLM server required)

5. **Engineering (real verification)**
   - Use the default Ollama server (`ollama serve` and `ollama pull qwen2.5:7b`), or any OpenAI-compatible server (set `FABRIC_CONFIG_PATH` to a config with the correct `base_url` and `model`).
   - Run: `python scripts/verify_working_real.py`
   - Expect: script exits 0; runlog contains **tool_call** and **tool_result** (model actually used tools); run completes with a final result. This confirms the fabric performs autonomously (uses tools and produces artifacts), not just that mocks work.
   - Alternatively, run manually: `fabric run "Create a tiny FastAPI app with /health and unit tests, runnable with uvicorn." --pack engineering` and inspect `.fabric/runs/<id>/runlog.jsonl` and `workspace/`.

6. **Research**
   - Same server:
     - `fabric run "Mini systematic review of post-quantum crypto performance." --pack research`
   - Expect: run uses web_search/fetch_url (if network allowed), writes files to workspace, ends with `action: "final"` and deliverables/citations.

### Automated tests

From the repo root with `pip install -e ".[dev]"`:

```bash
pytest tests/ -v
```

**Use the right technique for the job:** Mocked and unit tests give fast feedback and validate wiring, contracts, and behaviour in isolation. For **integration and "everything works together"** we rely on **at least a couple of E2E tests that run against a real LLM**. Those real-LLM E2E tests are essential to ensure the full stack is integrated and working as expected.

- **Full validation (required to assert system works):** Run with a real LLM so the real-LLM E2E tests run and pass (no skips). Use `python scripts/validate_full.py`; all 42 tests must run. If any are skipped, validation fails.
- **Fast CI:** `FABRIC_SKIP_REAL_LLM=1 pytest tests/ -v` runs 38 tests and skips the 4 real-LLM E2E tests. Use for quick feedback on wiring and unit/integration behaviour; it does not replace the need to run real-LLM E2E for integration assurance.

All Phase 1 checks are automated. With a real LLM: router, sandbox, config, packs, integration, **engineering E2E with real LLM** (tool_call, tool_result, artifacts), **research E2E with real LLM**, **API POST /run with real LLM**, and **scripts/verify_working_real.py** run as part of pytest. Local LLM bootstrap (start when unreachable) is tested with mocks in fast CI; with full validation the real bootstrap can be used to start the LLM before running tests.

**Real-LLM E2E (essential for integration):** We need at least a couple of end-to-end tests that run against a real LLM. They assert that the agent **uses tools** (runlog contains `tool_call` and `tool_result` events) and **produces artifacts** (e.g. workspace files). These tests are: `test_execute_task_engineering_real_llm`, `test_execute_task_research_pack_real_llm`, `test_api_post_run_real_llm`, and `test_verify_working_real_script`. For full validation they must **run** (not skip); use `scripts/validate_full.py` or run pytest with a real LLM available.

---

## Out of scope (for this MVP)

- Config file format and merging semantics are minimal (override only when path is set).
- No persistent vector store, MCP servers, or observability export.
- Shell sandbox does not enforce network blocking; `network_allowed` is enforced for research web tools only.
