# agentic-concierge: Architecture

**Purpose:** Layer boundaries, key classes, data flow, and extension points.
Read this before making structural changes or adding a new specialist pack.

See [DECISIONS.md](DECISIONS.md) for the *why* behind each major design choice.
See [BACKLOG.md](BACKLOG.md) for what is next.

---

## 1. Layer overview

agentic-concierge uses a strict hexagonal (ports-and-adapters) architecture.
Arrows show allowed import directions — the application core never imports
from infrastructure or interfaces.

```
┌─────────────────────────────────────────────────────────────────────┐
│  Interfaces  (entry points — wire everything together)              │
│                                                                     │
│   cli.py (Typer)                 http_api.py (FastAPI)              │
│   concierge run / serve / logs      GET /health                        │
│                                  POST /run  (blocking)              │
│                                  POST /run/stream  (SSE)            │
│                                  GET /runs/{id}/status              │
└──────────────────┬──────────────────────────────────────────────────┘
                   │ calls
┌──────────────────▼──────────────────────────────────────────────────┐
│  Application  (orchestration + ports)                               │
│                                                                     │
│   execute_task()  ·  _execute_pack_loop()  ·  resume_execute_task() │
│   _run_task_force_parallel()  ·  _merge_parallel_payloads()         │
│   orchestrate_task()  ·  recruit_specialist()  ·  llm_recruit_specialist() │
│                                                                     │
│   Ports (Protocol interfaces defined here):                         │
│     ChatClient  ·  RunRepository                                    │
│     SpecialistRegistry  ·  SpecialistPack                           │
└──────┬─────────────────────────────────┬────────────────────────────┘
       │ imports domain                  │ imports domain
┌──────▼──────────┐        ┌─────────────▼────────────────────────────┐
│  Domain         │        │  Infrastructure  (adapters)              │
│  (pure data)    │        │                                          │
│                 │        │  OllamaChatClient                        │
│  Task           │        │    → implements ChatClient               │
│  RunId          │        │  GenericChatClient (cloud / vLLM)        │
│  RunResult      │        │    → implements ChatClient               │
│  LLMResponse    │        │  FallbackChatClient (cloud quality gate) │
│  ToolCallRequest│        │    → wraps ChatClient                    │
│  RecruitError   │        │  FileSystemRunRepository                 │
│  FabricError    │        │    → implements RunRepository            │
└─────────────────┘        │  ConfigSpecialistRegistry                │
                           │    → implements SpecialistRegistry       │
                           │  BaseSpecialistPack                      │
                           │    → implements SpecialistPack           │
                           │  MCPAugmentedPack (MCP tool servers)     │
                           │  ContainerisedSpecialistPack (Podman)    │
                           │  engineering / research / enterprise packs│
                           │  sandbox · file / shell / web tools      │
                           │  llm_discovery · llm_bootstrap           │
                           │  telemetry (OpenTelemetry, optional)     │
                           └──────────────────────────────────────────┘

  Config  (cross-cutting — any layer may import)
  ┌────────────────────────────────────────────────────────────────────┐
  │  ConciergeConfig · ModelConfig · SpecialistConfig · MCPServerConfig   │
  │  CloudFallbackConfig · RunIndexConfig · TelemetryConfig            │
  │  load_config() [lru_cache] · capabilities.py · constants.py       │
  └────────────────────────────────────────────────────────────────────┘
```

---

## 2. Component map

```
src/agentic_concierge/
│
├── domain/
│   ├── models.py        Task · RunId · RunResult
│   │                    LLMResponse · ToolCallRequest
│   └── errors.py        FabricError · RecruitError
│
├── application/
│   ├── execute_task.py  Main use-case: recruit → create run → tool loop(s) → result
│   │                    _execute_pack_loop(): one specialist's tool-calling loop
│   │                    _run_task_force_parallel(): asyncio.gather for concurrent packs
│   │                    _merge_parallel_payloads(): combines parallel results
│   │                    _emit(): mirrors every event to optional event_queue (SSE)
│   ├── recruit.py       recruit_specialist() (keyword)
│   │                    llm_recruit_specialist() (LLM-driven, uses routing_model_key)
│   │                    infer_capabilities() · _greedy_select_specialists()
│   │                    RecruitmentResult(specialist_ids, required_capabilities, routing_method)
│   └── ports.py         ChatClient · RunRepository · SpecialistRegistry
│                        SpecialistPack  (Protocol interfaces)
│
├── infrastructure/
│   ├── chat/
│   │   ├── __init__.py      build_chat_client() — factory dispatches on ModelConfig.backend
│   │   ├── generic.py       GenericChatClient — bare OpenAI-compatible (no Ollama quirks)
│   │   ├── _parser.py       parse_chat_response() — shared across clients
│   │   └── fallback.py      FallbackChatClient — wraps client; applies FallbackPolicy
│   │                          FallbackPolicy: no_tool_calls | malformed_args | always
│   │                          pop_events() — drain cloud_fallback events for runlog
│   ├── ollama/
│   │   └── client.py        OllamaChatClient
│   │                          • POST /v1/chat/completions (OpenAI format)
│   │                          • native tool calling (tool_calls in response)
│   │                          • 400 retry on "does not support tools" models
│   ├── mcp/
│   │   ├── session.py       MCPSessionManager(config: MCPServerConfig)
│   │   │                      connect() / disconnect() (stdio subprocess or SSE)
│   │   │                      list_tools() → OpenAI-format defs with mcp__name__tool prefix
│   │   │                      call_tool(name, args) → result dict
│   │   ├── converter.py     mcp_tool_to_openai_def() — MCP tool → OpenAI function schema
│   │   └── augmented_pack.py MCPAugmentedPack(inner, sessions)
│   │                          aopen(): asyncio.gather all session connects
│   │                          aclose(): asyncio.gather all session disconnects
│   │                          tool_definitions: inner tools + MCP tools merged
│   │                          execute_tool(): dispatch to owning session or inner pack
│   ├── workspace/
│   │   ├── run_repository.py  FileSystemRunRepository
│   │   ├── run_directory.py   create_run_directory()
│   │   │                        → .concierge/runs/<uuid>/{workspace/, runlog.jsonl}
│   │   ├── run_log.py         append_event() — one JSON line per event
│   │   ├── run_index.py       RunIndexEntry · append_to_index() · search_index()
│   │   │                        semantic_search_index() (cosine similarity via Ollama)
│   │   │                        embed_text() via Ollama /api/embeddings
│   │   └── run_reader.py      list_runs() · read_run_events() → RunSummary
│   ├── specialists/
│   │   ├── base.py            BaseSpecialistPack
│   │   │                        holds: system_prompt, tool_map, tool_definitions
│   │   │                        async execute_tool() · aopen() (no-op) · aclose() (no-op)
│   │   ├── registry.py        ConfigSpecialistRegistry
│   │   │                        _DEFAULT_BUILDERS: built-in pack factories
│   │   │                        SpecialistConfig.builder: dynamic import for custom packs
│   │   │                        wraps with MCPAugmentedPack when mcp_servers non-empty
│   │   │                        wraps with ContainerisedSpecialistPack when container_image set
│   │   ├── engineering.py     build_engineering_pack()
│   │   │                        tools: shell, read_file, write_file, list_files
│   │   ├── research.py        build_research_pack()
│   │   │                        tools: web_search*, fetch_url*, write_file, read_file, list_files
│   │   │                        (* only when network_allowed=True)
│   │   ├── enterprise_research.py  build_enterprise_research_pack()
│   │   │                        tools: cross_run_search (queries run_index),
│   │   │                               web_search*, fetch_url*, read/write/list files
│   │   ├── containerised.py   ContainerisedSpecialistPack(inner, image)
│   │   │                        intercepts execute_tool("shell") → podman exec
│   │   ├── tool_defs.py       make_tool_def() · make_finish_tool_def()
│   │   └── prompts.py         SYSTEM_PROMPT_ENGINEERING · SYSTEM_PROMPT_RESEARCH
│   │                          SYSTEM_PROMPT_ENTERPRISE_RESEARCH
│   ├── tools/
│   │   ├── sandbox.py         SandboxPolicy · run_cmd() · safe_path()
│   │   │                        path-escape prevention + command allowlist
│   │   ├── shell_tools.py     run_shell() — wraps run_cmd
│   │   ├── file_tools.py      read_text() · write_text() · list_tree()
│   │   └── web_tools.py       web_search() · fetch_url()
│   ├── llm_discovery.py       resolve_llm() — probe backend, select model
│   │                            discover_ollama_models() / discover_openai_models()
│   │                            select_model() with param-size sort key
│   ├── llm_bootstrap.py       ensure_llm_available() — start Ollama if needed
│   └── telemetry.py           setup_telemetry() · get_tracer()
│                                _NoOpSpan / _NoOpTracer — graceful no-op without OTEL
│                                spans: fabric.execute_task / fabric.llm_call / fabric.tool_call
│
├── interfaces/
│   ├── cli.py            Typer app:
│   │                       concierge run [--pack] [--model-key] [--network-allowed] [--verbose]
│   │                       concierge serve [--host] [--port]
│   │                       concierge logs list [--workspace] [--limit]
│   │                       concierge logs show RUN_ID [--workspace] [--kinds]
│   │                       concierge logs search QUERY [--workspace] [--limit]
│   └── http_api.py       FastAPI:
│                           GET  /health
│                           POST /run               (blocking; returns finish_task payload + _meta)
│                           POST /run/stream        (SSE; streams all events until _run_done_)
│                           GET  /runs/{id}/status  (completed | running | 404)
│
└── config/
    ├── schema.py         ConciergeConfig · ModelConfig · SpecialistConfig
    │                       MCPServerConfig · CloudFallbackConfig · RunIndexConfig
    │                       TelemetryConfig · DEFAULT_CONFIG (Ollama @ localhost:11434)
    ├── loader.py         load_config() — lru_cache(maxsize=1)
    │                       reads CONCIERGE_CONFIG_PATH env var (JSON or YAML)
    ├── capabilities.py   CAPABILITY_KEYWORDS · infer_capabilities()
    └── constants.py      MAX_TOOL_OUTPUT_CHARS · MAX_LLM_CONTENT_IN_RUNLOG_CHARS
                          LLM_DISCOVERY_TIMEOUT_S · SHELL_DEFAULT_TIMEOUT_S
```

---

## 3. Task execution: data flow

### ASCII flow (single pack)

```
 User / HTTP client
       │
       │  Task(prompt, specialist_id?, model_key, network_allowed)
       ▼
  execute_task()
       │
       ├─ [specialist_id is None?]
       │    llm_recruit_specialist(prompt, config)   # LLM-driven, routing_model_key
       │      OR recruit_specialist(prompt, config)  # keyword fallback
       │      → RecruitmentResult(specialist_ids, required_capabilities, routing_method)
       │
       ├─ [cloud_fallback configured?]
       │    wrap chat_client with FallbackChatClient(local, cloud, policy)
       │
       ├─ RunRepository.create_run()
       │    creates .concierge/runs/<uuid>/workspace/
       │    → (RunId, run_dir, workspace_path)
       │
       ├─ [task_force_mode == "parallel" and len(specialist_ids) > 1]?
       │    _run_task_force_parallel(...)
       │      asyncio.gather(_execute_pack_loop × N)
       │      → _merge_parallel_payloads() → combined payload
       │
       └─ [sequential, default]
            for each specialist_id:
              SpecialistRegistry.get_pack(id, workspace_path, network_allowed)
                → wraps with MCPAugmentedPack  (if mcp_servers)
                → wraps with ContainerisedSpecialistPack  (if container_image)
              _execute_pack_loop(pack, messages, …)
                previous pack's finish_payload forwarded as context
```

### _execute_pack_loop detail

```
 _execute_pack_loop()
       │
       ├─ await pack.aopen()    ← MCPAugmentedPack connects sessions; no-op for plain packs
       │
       └─ Tool loop (up to max_steps, default 40)
              │
              ├─ append_event("llm_request")  + _emit(event_queue, …)
              ├─ ChatClient.chat(messages, model, tools=pack.tool_definitions)
              │    [FallbackChatClient: try local → maybe retry on cloud]
              ├─ append_event("llm_response")  + _emit(…)
              │    drain FallbackChatClient.pop_events() → cloud_fallback events
              │
              └─ for each tool_call in response.tool_calls:
                   │
                   ├─ append_event("tool_call")  + _emit(…)
                   │
                   ├─ [tool_name == finish_task]
                   │    guard: must have called at least one non-finish tool first
                   │    validate required fields present
                   │    ├─ missing / no prior work → send error to LLM, continue loop
                   │    └─ valid → append_event("tool_result")  + _emit(…)
                   │              set finish_payload, break loop
                   │
                   └─ [regular tool]
                        await pack.execute_tool(name, args)
                          runs inside SandboxPolicy (path-escape check, command allowlist)
                        ├─ success       → append_event("tool_result")  + _emit(…)
                        ├─ PermissionError → append_event("tool_error") + _emit(…)
                        │                    append_event("security_event") + _emit(…)
                        └─ other error   → append_event("tool_error")  + _emit(…)
                        result appended to messages → next LLM call
       │
       └─ await pack.aclose()   ← in finally block (MCP cleanup)
```

After the pack loop(s):

```
  append_event("run_complete") + _emit(event_queue, "run_complete", …)
  append entry to run_index.jsonl (cross-run memory)
  _emit(event_queue, "_run_done_", …)   ← terminates SSE stream
  return RunResult(…)
```

### SSE streaming (POST /run/stream)

```
  POST /run/stream
       │
       ├─ asyncio.Queue(maxsize=256)  ← event_queue
       │
       ├─ asyncio.create_task(_run_task_background())
       │    calls execute_task(…, event_queue=event_queue)
       │    on exception: put _run_error_ sentinel
       │
       └─ StreamingResponse(_sse_event_generator(event_queue))
              yields "data: {json}\n\n" for each event
              stops on _run_done_ or _run_error_ sentinel
```

### Sequence diagram (happy path, single pack)

```
 CLI/HTTP   execute_task  recruit  SpecReg  RunRepo   ChatClient  Pack
    │            │           │        │        │           │        │
    │──Task──────▶           │        │        │           │        │
    │            │──prompt──▶│        │        │           │        │
    │            │◀──ids─────│        │        │           │        │
    │            │──get_pack──────────▶        │           │        │
    │            │◀──pack────────────│        │           │        │
    │            │──create_run────────────────▶│           │        │
    │            │◀──(run_id, dirs)───────────│           │        │
    │            │                            │           │        │
    │         ┌──┤ step 0..N                  │           │        │
    │         │  │──append(llm_request)───────▶           │        │
    │         │  │──chat(msgs, tools)─────────────────────▶        │
    │         │  │◀──LLMResponse(tool_calls)─────────────│        │
    │         │  │──append(llm_response)──────▶           │        │
    │         │  │──execute_tool(name, args)───────────────────────▶│
    │         │  │◀──result dict──────────────────────────────────│
    │         │  │──append(tool_result)───────▶           │        │
    │         └──┤ finish_task (valid) → break            │        │
    │            │                                        │        │
    │            │──append(run_complete)──────▶                    │
    │◀──RunResult│                                                  │
```

---

## 4. Runlog events

Every run produces `.concierge/runs/<id>/runlog.jsonl`.
Each line is a JSON record:

```json
{"ts": 1708800000.123, "kind": "<kind>", "step": "step_0", "payload": {...}}
```

| `kind` | When | Key payload fields |
|---|---|---|
| `recruitment` | Specialist(s) selected | `specialist_id`, `specialist_ids`, `required_capabilities`, `routing_method`, `is_task_force` |
| `task_force_parallel` | Parallel task force started | `specialist_ids`, `mode: "parallel"` |
| `pack_start` | One specialist starts (task forces) | `specialist_id`, `pack_index` |
| `llm_request` | Before each LLM call | `step`, `message_count` |
| `llm_response` | After each LLM call | `content` (truncated to 2 000 chars), `tool_calls` |
| `cloud_fallback` | Local model fell back to cloud | `reason`, `local_model`, `cloud_model` |
| `tool_call` | Before executing a tool | `tool`, `args` |
| `tool_result` | Successful tool result, or accepted `finish_task` | `tool`, `result` |
| `tool_error` | Tool raised an exception | `tool`, `error_type`, `error_message` |
| `security_event` | `PermissionError` from tool (sandbox escape) | `event_type: "sandbox_violation"`, `tool`, `error_message` |
| `run_complete` | Run finished successfully | `run_id`, `specialist_ids`, `task_force_mode` |

`tool_error` and `security_event` are both emitted when a `PermissionError` occurs — the former for error classification, the latter as an explicit audit trail.

`run_complete` is written at the end of every successful run. `GET /runs/{id}/status` uses this event for completion detection.

---

## 5. Extension points

### New LLM backend

Implement the `ChatClient` protocol (`application/ports.py`):

```python
class MyBackendClient:
    async def chat(
        self, messages, model, *, tools=None,
        temperature, top_p, max_tokens,
    ) -> LLMResponse: ...
```

Inject at the interface layer. No changes to `execute_task` or any other layer.

### New specialist pack

**Option A — config-driven (no core code change):**

1. Write a factory: `build_my_pack(workspace_path: str, network_allowed: bool) -> SpecialistPack`
2. In your `CONCIERGE_CONFIG_PATH` config, set `builder: "mymodule:build_my_pack"` on the specialist entry.

**Option B — built-in:**

1. Add `infrastructure/specialists/my_pack.py` with `build_my_pack()`.
2. Register in `_DEFAULT_BUILDERS` in `infrastructure/specialists/registry.py`.
3. Add a specialist entry to `DEFAULT_CONFIG` in `config/schema.py`.
4. Add capability keywords to `config/capabilities.py`.

Both options use `BaseSpecialistPack` and `tool_defs.make_tool_def()` / `make_finish_tool_def()`.

### New tool

Add a function in `infrastructure/tools/` that accepts a `SandboxPolicy` and returns `dict`.
Register it in the appropriate pack's factory using `make_tool_def(name, description, parameters_schema)`.

### New MCP server (zero Python)

Add an `mcp_servers` entry to any specialist in config — see [MCP_INTEGRATIONS.md](MCP_INTEGRATIONS.md).

---

## 6. Config and startup

```
CONCIERGE_CONFIG_PATH (env var, optional JSON or YAML)
        │
        ▼
 load_config()  ← lru_cache(maxsize=1): read once per process
        │              call load_config.cache_clear() to force reload
        ▼
 ConciergeConfig
   ├── models: {key → ModelConfig(base_url, model, backend, temperature, …)}
   ├── specialists: {id → SpecialistConfig(description, keywords, builder?, mcp_servers, container_image)}
   ├── routing_model_key: str  (default "fast")
   ├── task_force_mode: str    (default "sequential")
   ├── local_llm_ensure_available: bool  (default True)
   ├── local_llm_start_cmd: list[str]   (default ["ollama", "serve"])
   ├── auto_pull_if_missing: bool  (default True)
   ├── run_index: RunIndexConfig(embedding_model?, embedding_base_url?)
   ├── cloud_fallback: CloudFallbackConfig(model_key, policy)?
   └── telemetry: TelemetryConfig(enabled, exporter, otlp_endpoint)?

 CLI / HTTP startup:
   resolve_llm(config, model_key)
     ├── [ensure_available] ensure_llm_available() — start server if down
     ├── discover_ollama_models()  or  discover_openai_models()
     └── select_model() — prefer configured model; fall back to smallest
         returns ResolvedLLM(base_url, model, model_config)
```

---

## 7. Dependency rule summary

| Layer | May import from |
|---|---|
| `domain` | stdlib only |
| `application` | `domain`, `config` |
| `infrastructure` | `domain`, `application.ports`, `config` |
| `interfaces` | all layers |
| `config` | stdlib + pydantic only |

Violations of this rule break testability: `execute_task` tests run with
mocked ports and never touch a real LLM or filesystem because the application
layer is kept clean.

---

## 8. Phase 12 additions (Quality Gates, Orchestrator, Session Continuation)

### 8.1 Engineering Quality Gate (P12-1 to P12-4)

```
_execute_pack_loop()
  ├── Gate 1: no prior tool call before finish_task → error to LLM
  ├── Gate 2: required fields missing → error to LLM
  └── Gate 3: pack.validate_finish_payload(args) → str or None
              EngineeringSpecialistPack.validate_finish_payload():
                if tests_verified is False → "run run_tests first" error
              BaseSpecialistPack default: always None (no gate)

run_tests(policy, framework, path, timeout_s) → dict
  Auto-detects: Cargo.toml→cargo, package.json+test→npm, pytest.ini/pyproject/test_*.py→pytest
  Runs via run_cmd() (sandbox allowlist applies)
  Returns: {passed, failed_count, error_count, summary, output, framework}
```

### 8.2 LLM Orchestrator (P12-5 to P12-10)

The orchestrator replaces the naive `llm_recruit_specialist` call at the top of `execute_task()`:

```
execute_task()
  if task.specialist_id is None:
    plan = await orchestrate_task(prompt, config, chat_client, model=routing_model)
      ├── One LLM call with create_plan tool
      ├── Parses: assignments (specialist_id + brief), mode, synthesis_required, reasoning
      ├── Filters unknown specialist IDs
      ├── Forces synthesis_required=True when len(assignments) > 1
      └── Falls back to llm_recruit_specialist on any error (zero regression)
    specialist_ids = [a.specialist_id for a in plan.specialist_assignments]
    task_force_mode = plan.mode  # may override config.task_force_mode
  else:
    specialist_ids = [task.specialist_id]  # explicit, no orchestrator call

  # Brief injection (per specialist):
  brief_text = _get_brief(plan, specialist_id)  # "" if plan is None
  if brief_text:
    user_content += f"\n\nYour specific assignment:\n{brief_text}"

  # After all specialists complete:
  if plan.synthesis_required and len(all_payloads) > 1:
    final_payload = await _synthesise_results(...)  # one LLM call with synthesise_results tool
    # Exception → fallback to last specialist's payload (non-fatal)
```

**Runlog events added by orchestrator:**
- `orchestration_plan` — emitted when `routing_method="orchestrator"` with assignments/mode/synthesis_required/reasoning

**CLI command:** `concierge plan "<prompt>"` — calls `orchestrate_task`, prints Rich panel, no run directory created.

### 8.3 Session Continuation (P12-11 to P12-13)

```
Checkpoint file: {run_dir}/checkpoint.json  (plain JSON, atomic write via .tmp + rename)

RunCheckpoint fields:
  run_id, run_dir, workspace_path, task_prompt
  specialist_ids, completed_specialists, payloads
  task_force_mode, model_key, routing_method, required_capabilities
  orchestration_plan (serialized dict or None)
  created_at, updated_at

execute_task() lifecycle:
  1. After create_run() + recruitment: _create_initial_checkpoint()
  2. After each sequential specialist: _update_checkpoint(completed=..., payloads=...)
  3. After run_complete event: _delete_run_checkpoint()

resume_execute_task(run_id, workspace_root, ...)
  ├── load_checkpoint() → ValueError if missing or all complete
  ├── Reconstructs plan from checkpoint.orchestration_plan
  ├── Loops specialists: skips completed, runs remaining
  ├── Updates checkpoint after each specialist
  ├── Emits run_complete and deletes checkpoint
  └── Returns RunResult

find_resumable_runs(workspace_root):
  Scans */checkpoint.json; returns run_ids with no run_complete in runlog
```

**CLI commands added:**
- `concierge resume <run-id>` — loads checkpoint, resumes run, streams events
- `concierge logs list` — now shows `(resumable)` next to interrupted run IDs

---

## 9. Phase 13: Rust thin launcher

The `launcher/` Rust crate adds a static ~5 MB binary that bootstraps the Python environment and
then exec-replaces itself with the Python `concierge` binary. No Python or pip required to get started.

### Launcher flow

```
User runs: concierge [args]
    │
    ├── parse_launcher_args() → self_update?
    │
    ├── launcher_config()
    │     CONCIERGE_DATA_DIR   → data_dir (default: ~/.local/share/agentic-concierge)
    │     CONCIERGE_NO_UPDATE_CHECK=1 → skip update hint
    │     CONCIERGE_EXTRA      → pip extras (e.g. "mcp,otel")
    │
    ├── [if --self-update]  check_latest_release → apply_update → upgrade_package → exit 0
    │
    ├── [else if !skip_update]  check_latest_release → is_newer → print hint (never blocks)
    │
    ├── ensure_environment(config)
    │     Fast path: venv/bin/concierge exists? → return path.
    │     First-time:
    │       try_system_python() → >= 3.10 in PATH?
    │       If None: ensure_uv() → download uv from GitHub, extract with system tar
    │       python3 -m venv  OR  uv venv --python 3.12
    │       pip install --upgrade agentic-concierge[{extra}]
    │       write installed_version
    │       return venv/bin/concierge
    │
    └── exec_python_concierge(bin)
          exec() replaces process image — Python inherits launcher PID, correct signals
```

### Module dependency graph

```
main.rs → config.rs        (data_dir, paths, env constants)
       → update.rs → config.rs   (GitHub Releases API; atomic self-update)
       → setup.rs  → config.rs   (Python/venv/pip; most replaceable module)
       → exec.rs   (no deps)     (execv the Python concierge binary)
```

`main.rs` is the **only** file that imports from other modules. No module imports another.
This enforces the single-public-API-surface rule: each module can be replaced independently
in future phases without touching `main.rs`.

### Future evolution paths

| Module | Status |
|--------|--------|
| `setup.rs` | Phase 14 done — pure-Rust `flate2`+`tar` extraction; no system `tar` dep |
| `update.rs` | Phase 14 done — Ed25519 sig verification before apply (ADR-017) |
| `exec.rs`   | Phase 14 done — `#[cfg(unix)]` guard; Phase 15: Windows `CreateProcess` |
| `config.rs` | Stable; env-var contract unlikely to change |

### Distribution

| Channel | Who | How |
|---------|-----|-----|
| GitHub Releases binary | End users (Linux) | `install.sh` one-liner or direct download |
| PyPI wheel | Developers, CI | `pip install agentic-concierge` |
| Docker (GHCR) | Operators | `docker compose up` |

The launcher binary is a **thin distribution shim only** — all application logic stays in Python.

---

## 10. Phase 14: Hot-path analysis

**Finding**: The Python application is I/O-bound on every hot path. No PyO3 extension
module is justified at current scale.

| Call site | Type | Typical latency | Rust (PyO3) benefit |
|-----------|------|-----------------|---------------------|
| LLM HTTP call | I/O | 100 ms – 10 s | None |
| Tool subprocess | I/O | 10 ms – 5 s | None |
| `safe_path()` | CPU | ~5 μs | Negligible |
| `cosine_similarity()` | CPU | ~50 μs/pair | Only if index > 50 k entries |
| JSON parsing | CPU | ~10 μs (C-backed) | None |

**Verdict**: No PyO3 extension justified at current scale. The one candidate,
`cosine_similarity`, is already superseded by ChromaDB for large-scale deployments.
Deferred to Phase 16 pending profiling evidence at production scale (> 50 k entries).

**Phase 14 Rust changes** (launcher only — not application):
- `setup.rs`: replaced `tar xzf` subprocess with `flate2` + `tar` pure-Rust extraction.
  Removes the system `tar` dependency; works on macOS, Linux musl, and future Windows.
- `update.rs`: added Ed25519 signature verification (`ed25519-dalek`) before atomic binary
  rename. See ADR-017 for key management and failure policy.
- `exec.rs`: `#[cfg(unix)]` guard documents the Linux + macOS POSIX path; Phase 15 will
  add the `#[cfg(windows)]` branch using `CreateProcess` + `WaitForSingleObject`.
- CI + `install.sh`: macOS targets (`x86_64/aarch64-apple-darwin`) added to all workflows.
