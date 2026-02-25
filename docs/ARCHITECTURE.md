# agent-fabric: Architecture

**Purpose:** Layer boundaries, key classes, data flow, and extension points.
Read this before making structural changes or adding a new specialist pack.

See [DECISIONS.md](DECISIONS.md) for the *why* behind each major design choice.
See [BACKLOG.md](BACKLOG.md) for what is next.

---

## 1. Layer overview

agent-fabric uses a strict hexagonal (ports-and-adapters) architecture.
Arrows show allowed import directions — the application core never imports
from infrastructure or interfaces.

```
┌─────────────────────────────────────────────────────────────────────┐
│  Interfaces  (entry points — wire everything together)              │
│                                                                     │
│   cli.py (Typer)                 http_api.py (FastAPI)              │
│   fabric run / serve / logs      GET /health                        │
│                                  POST /run  (blocking)              │
│                                  POST /run/stream  (SSE)            │
│                                  GET /runs/{id}/status              │
└──────────────────┬──────────────────────────────────────────────────┘
                   │ calls
┌──────────────────▼──────────────────────────────────────────────────┐
│  Application  (orchestration + ports)                               │
│                                                                     │
│   execute_task()  ·  _execute_pack_loop()                           │
│   _run_task_force_parallel()  ·  _merge_parallel_payloads()         │
│   recruit_specialist()  ·  llm_recruit_specialist()                 │
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
  │  FabricConfig · ModelConfig · SpecialistConfig · MCPServerConfig   │
  │  CloudFallbackConfig · RunIndexConfig · TelemetryConfig            │
  │  load_config() [lru_cache] · capabilities.py · constants.py       │
  └────────────────────────────────────────────────────────────────────┘
```

---

## 2. Component map

```
src/agent_fabric/
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
│   │   │                        → .fabric/runs/<uuid>/{workspace/, runlog.jsonl}
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
│   │                       fabric run [--pack] [--model-key] [--network-allowed] [--verbose]
│   │                       fabric serve [--host] [--port]
│   │                       fabric logs list [--workspace] [--limit]
│   │                       fabric logs show RUN_ID [--workspace] [--kinds]
│   │                       fabric logs search QUERY [--workspace] [--limit]
│   └── http_api.py       FastAPI:
│                           GET  /health
│                           POST /run               (blocking; returns finish_task payload + _meta)
│                           POST /run/stream        (SSE; streams all events until _run_done_)
│                           GET  /runs/{id}/status  (completed | running | 404)
│
└── config/
    ├── schema.py         FabricConfig · ModelConfig · SpecialistConfig
    │                       MCPServerConfig · CloudFallbackConfig · RunIndexConfig
    │                       TelemetryConfig · DEFAULT_CONFIG (Ollama @ localhost:11434)
    ├── loader.py         load_config() — lru_cache(maxsize=1)
    │                       reads FABRIC_CONFIG_PATH env var (JSON or YAML)
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
       │    creates .fabric/runs/<uuid>/workspace/
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

Every run produces `.fabric/runs/<id>/runlog.jsonl`.
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
2. In your `FABRIC_CONFIG_PATH` config, set `builder: "mymodule:build_my_pack"` on the specialist entry.

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
FABRIC_CONFIG_PATH (env var, optional JSON or YAML)
        │
        ▼
 load_config()  ← lru_cache(maxsize=1): read once per process
        │              call load_config.cache_clear() to force reload
        ▼
 FabricConfig
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
