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
┌─────────────────────────────────────────────────────────────┐
│  Interfaces  (entry points — wire everything together)      │
│                                                             │
│   cli.py (Typer)            http_api.py (FastAPI)           │
│   `fabric run / serve`      GET /health · POST /run         │
└──────────────────┬──────────────────────────────────────────┘
                   │ calls
┌──────────────────▼──────────────────────────────────────────┐
│  Application  (orchestration + ports)                       │
│                                                             │
│   execute_task()            recruit_specialist()            │
│                                                             │
│   Ports (Protocol interfaces defined here):                 │
│     ChatClient · RunRepository                              │
│     SpecialistRegistry · SpecialistPack                     │
└──────┬─────────────────────────────────┬────────────────────┘
       │ imports domain                  │ imports domain
┌──────▼──────────┐        ┌─────────────▼──────────────────────┐
│  Domain         │        │  Infrastructure  (adapters)        │
│  (pure data)    │        │                                    │
│                 │        │  OllamaChatClient                  │
│  Task           │        │    → implements ChatClient         │
│  RunId          │        │  FileSystemRunRepository           │
│  RunResult      │        │    → implements RunRepository      │
│  LLMResponse    │        │  ConfigSpecialistRegistry          │
│  ToolCallRequest│        │    → implements SpecialistRegistry │
│  RecruitError   │        │  BaseSpecialistPack                │
│  FabricError    │        │    → implements SpecialistPack     │
└─────────────────┘        │  engineering / research packs      │
                           │  sandbox · file / shell / web tools│
                           │  llm_discovery · llm_bootstrap     │
                           └────────────────────────────────────┘

  Config  (cross-cutting — any layer may import)
  ┌──────────────────────────────────────────────────────────┐
  │  FabricConfig · ModelConfig · SpecialistConfig           │
  │  load_config() [lru_cache] · constants.py                │
  └──────────────────────────────────────────────────────────┘
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
│   ├── execute_task.py  Main use-case: recruit → create run → tool loop → result
│   ├── recruit.py       recruit_specialist(): keyword scoring → specialist_id
│   └── ports.py         ChatClient · RunRepository · SpecialistRegistry
│                        SpecialistPack  (Protocol interfaces)
│
├── infrastructure/
│   ├── ollama/
│   │   └── client.py        OllamaChatClient
│   │                          • POST /v1/chat/completions (OpenAI format)
│   │                          • native tool calling (tool_calls in response)
│   │                          • 400 retry with minimal payload on older Ollama
│   ├── workspace/
│   │   ├── run_repository.py FileSystemRunRepository
│   │   ├── run_directory.py  create_run_directory()
│   │   │                       → .fabric/runs/<uuid>/{workspace/, runlog.jsonl}
│   │   └── run_log.py        append_event() — one JSON line per event
│   ├── specialists/
│   │   ├── base.py           BaseSpecialistPack
│   │   │                       holds: system_prompt, tool map, finish_tool_def
│   │   │                       exposes: tool_definitions, execute_tool()
│   │   ├── registry.py       ConfigSpecialistRegistry
│   │   │                       • _DEFAULT_BUILDERS for built-in packs
│   │   │                       • dynamic import via SpecialistConfig.builder
│   │   ├── engineering.py    build_engineering_pack()
│   │   │                       tools: shell, read_file, write_file, list_files
│   │   ├── research.py       build_research_pack()
│   │   │                       tools: web_search*, fetch_url*, write_file,
│   │   │                              read_file, list_files   (* if network_allowed)
│   │   ├── tool_defs.py      make_tool_def() · make_finish_tool_def()
│   │   │                       READ/WRITE/LIST_FILES_TOOL_DEF (shared constants)
│   │   └── prompts.py        SYSTEM_PROMPT_ENGINEERING · SYSTEM_PROMPT_RESEARCH
│   ├── tools/
│   │   ├── sandbox.py        SandboxPolicy · run_cmd() · safe_path()
│   │   │                       path-escape prevention + command allowlist
│   │   ├── shell_tools.py    run_shell() — wraps run_cmd
│   │   ├── file_tools.py     read_text() · write_text() · list_tree()
│   │   └── web_tools.py      web_search() · fetch_url()
│   ├── llm_discovery.py      resolve_llm() — probe backend, select model
│   │                           discover_ollama_models() / discover_openai_models()
│   │                           select_model() with param-size sort key
│   └── llm_bootstrap.py      ensure_llm_available() — start Ollama if needed
│
├── interfaces/
│   ├── cli.py            Typer app: `fabric run --verbose` / `fabric serve`
│   └── http_api.py       FastAPI: GET /health · POST /run
│
└── config/
    ├── schema.py         FabricConfig · ModelConfig · SpecialistConfig
    │                       DEFAULT_CONFIG (Ollama @ localhost:11434)
    ├── loader.py         load_config() — lru_cache(maxsize=1)
    │                       reads FABRIC_CONFIG_PATH env var
    └── constants.py      MAX_TOOL_OUTPUT_CHARS · MAX_LLM_CONTENT_IN_RUNLOG_CHARS
                          LLM_DISCOVERY_TIMEOUT_S · LLM_CHAT_DEFAULT_TIMEOUT_S
                          SHELL_DEFAULT_TIMEOUT_S · LLM_PULL_TIMEOUT_S
```

---

## 3. Task execution: data flow

### ASCII flow

```
 User / HTTP client
       │
       │  Task(prompt, specialist_id?, model_key, network_allowed)
       ▼
  execute_task()
       │
       ├─ [specialist_id is None?]
       │    recruit_specialist(prompt, config)
       │      keyword scoring → specialist_id
       │
       ├─ SpecialistRegistry.get_pack(id, workspace_path, network_allowed)
       │    returns SpecialistPack
       │      system_prompt, tool_definitions, finish_tool_name,
       │      finish_required_fields, execute_tool()
       │
       ├─ RunRepository.create_run()
       │    creates .fabric/runs/<uuid>/workspace/
       │    returns (RunId, run_dir, workspace_path)
       │
       └─ Tool loop  (up to max_steps, default 40)
             │
             ├─ append_event("llm_request")
             ├─ ChatClient.chat(messages, model, tools=pack.tool_definitions)
             ├─ append_event("llm_response")
             │
             └─ for each tool_call in response.tool_calls:
                  │
                  ├─ [tool_name == finish_task]
                  │    validate required fields present
                  │    ├─ missing → send error result to LLM, continue loop
                  │    └─ valid  → append_event("tool_result")
                  │               set finish_payload, break loop
                  │
                  └─ [regular tool]
                       SpecialistPack.execute_tool(name, args)
                         runs inside SandboxPolicy
                       ├─ success       → append_event("tool_result")
                       ├─ PermissionError → append_event("tool_error") +
                       │                    append_event("security_event")
                       └─ other error   → append_event("tool_error")
                       result appended to messages → next LLM call

       Returns RunResult(run_id, run_dir, workspace_path,
                         specialist_id, model_name, payload)
```

### Sequence diagram (happy path)

```
 CLI/HTTP   execute_task  recruit  SpecReg  RunRepo   ChatClient  Pack
    │            │           │        │        │           │        │
    │──Task──────▶           │        │        │           │        │
    │            │──prompt──▶│        │        │           │        │
    │            │◀──id──────│        │        │           │        │
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
    │            │                            │           │        │
    │◀──RunResult│                            │           │        │
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
| `llm_request` | Before each LLM call | `step`, `message_count` |
| `llm_response` | After each LLM call | `content` (truncated to 2 000 chars), `tool_calls` |
| `tool_call` | Before executing a tool | `tool`, `args` |
| `tool_result` | Successful tool call, or accepted `finish_task` | `tool`, `result` |
| `tool_error` | Tool raised an exception | `tool`, `error_type`, `error_message` |
| `security_event` | `PermissionError` from tool (sandbox escape attempt) | `event_type: "sandbox_violation"`, `tool`, `error_message` |

`tool_error` and `security_event` are emitted together when a `PermissionError`
occurs — the former for the error classification, the latter as an explicit audit trail.

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
2. In your `FABRIC_CONFIG_PATH` YAML, set `builder: "mymodule:build_my_pack"` on the specialist entry.

**Option B — built-in:**

1. Add `infrastructure/specialists/mypacks.py` with a `build_my_pack()` factory.
2. Register in `_DEFAULT_BUILDERS` in `infrastructure/specialists/registry.py`.
3. Add the specialist entry to `DEFAULT_CONFIG` in `config/schema.py`.

Both options use `BaseSpecialistPack` and `tool_defs.make_tool_def()` /
`make_finish_tool_def()` to build the tool definitions.

### New tool

Add a function in `infrastructure/tools/` that accepts a `SandboxPolicy` and
returns a `dict`. Register it in the appropriate pack's factory using
`make_tool_def(name, description, parameters)` for the OpenAI definition.

---

## 6. Config and startup

```
FABRIC_CONFIG_PATH (env var, optional)
        │
        ▼
 load_config()  ← lru_cache(maxsize=1): read once per process
        │              call load_config.cache_clear() to force reload
        ▼
 FabricConfig
   ├── models: {key → ModelConfig(base_url, model, temperature, …)}
   ├── specialists: {id → SpecialistConfig(description, keywords, builder?)}
   ├── local_llm_ensure_available: bool  (default True)
   └── local_llm_start_cmd: list[str]   (default ["ollama", "serve"])

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
