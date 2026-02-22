# agent-fabric: Target Architecture

This document defines the **target architecture** for agent-fabric. We are building from the ground up; the previous code was a throwaway PoC. This design replaces it with a clear structure, good engineering practices, and alignment with the vision (Ollama-first, task → recruit task force, quality-first).

---

## 1. Design principles

- **Layered architecture** — Domain has no I/O; application depends on abstractions (ports); infrastructure implements them. Interfaces (CLI, API) wire everything and depend on application + infrastructure.
- **Ollama-first** — Local inference is via Ollama by default; the LLM is behind an abstraction so we can swap or add backends without polluting the core.
- **Explicit naming** — Modules, classes, and functions have clear, consistent names that reflect their responsibility. No prototype-style `_v1` or vague `supervisor`/`router` at the core.
- **Single responsibility** — Each module and class has one reason to change. Use cases are thin; domain is pure; infrastructure is adapters only.
- **Testability** — Domain and application are testable without real Ollama or file system; infrastructure is tested with fakes or integration tests.

---

## 2. Layers and responsibilities

| Layer | Responsibility | Depends on | No dependency on |
|-------|----------------|------------|-------------------|
| **Domain** | Entities, value objects, core rules. What is a Run, a Task, a Capability, a Specialist? | Nothing (pure) | I/O, HTTP, Ollama, config |
| **Application** | Use cases: “execute a task”, “recruit specialists”. Orchestration logic. | Domain, ports (abstract interfaces) | Concrete Ollama, concrete tools, concrete storage |
| **Infrastructure** | Ollama client, run directory and run log, tool implementations (shell, file, web), config loading. | Domain (types only where needed) | Application use-case internals |
| **Interfaces** | CLI and HTTP API. Parse args, load config, call use cases, return responses. | Application, Infrastructure, Config | — |

**Dependency rule:** Inner layers do not depend on outer layers. Domain ← Application ← (Infrastructure, Interfaces). Infrastructure and Interfaces can depend on Application and Config.

---

## 3. Package layout (target and current)

**Current layout** — single code path; **src layout**; package **`agent_fabric`** (consistent with repo name agent-fabric).

```
src/agent_fabric/
  domain/                    # Pure domain
    __init__.py
    models.py                # RunId, Task, RunResult
    errors.py                # FabricError, RecruitError, ToolExecutionError

  application/               # Use cases and orchestration
    __init__.py
    ports.py                 # ChatClient, RunRepository, SpecialistPack, SpecialistRegistry
    execute_task.py          # execute_task use case: recruit → run → tool loop
    recruit.py               # recruit_specialist (keyword-based)
    json_parsing.py          # extract_json (model output)

  config/                    # Configuration
    __init__.py
    schema.py                # FabricConfig, ModelConfig, SpecialistConfig (Ollama defaults)
    loader.py                # load_config from FABRIC_CONFIG_PATH or default

  infrastructure/            # Adapters
    __init__.py
    ollama/
      client.py              # OllamaChatClient (implements ChatClient)
    workspace/
      run_directory.py       # create_run_directory()
      run_log.py             # append_event()
      run_repository.py      # FileSystemRunRepository (composes the two above)
    tools/
      sandbox.py, file_tools.py, shell_tools.py, web_tools.py
    specialists/
      base.py                # BaseSpecialistPack
      engineering.py, research.py, prompts.py
      registry.py            # ConfigSpecialistRegistry

  interfaces/
    cli.py                   # Typer app: run, serve (entrypoint: fabric)
    http_api.py              # FastAPI: GET /health, POST /run
```

Repo root also has: **examples/** (example config, e.g. `examples/ollama.json`), **tests/**, **docs/**, **scripts/**.

**Naming:** Modules `snake_case` (e.g. `execute_task.py`, `run_log.py`). Classes `PascalCase`. See ENGINEERING.md for full conventions.

**Naming conventions** (see also ENGINEERING.md):

- **Modules:** `snake_case` (e.g. `execute_task.py`, `run_log.py`).
- **Classes:** `PascalCase`. Domain: `Run`, `RunId`, `Task`, `Capability`. Infrastructure: `OllamaChatClient`, `RunRepository`.
- **Functions:** `snake_case`. Use-case entry: `execute_task`. Internal: `_parse_tool_response`.
- **Constants:** `UPPER_SNAKE` for true constants; config keys follow schema.
- **Private:** Leading `_` for module-private (e.g. `_default_config()`).

---

## 4. Key abstractions (ports)

The application layer depends on **ports** (abstract interfaces), not concrete implementations.

- **ChatClient** (port) — `async def chat(messages, model, **params) -> str`. Implemented by `OllamaChatClient` (and later, e.g. OpenAI fallback).
- **RunRepository** (port) — Create run, resolve workspace path, append run-log events. Implemented by `FileSystemRunRepository` (run_directory + run_log).
- **ToolExecutor** (port) — Execute a tool by name with args; returns result dict. Implemented by tool registry that delegates to sandboxed file/shell/web tools.
- **SpecialistRegistry** (port) — Resolve specialist pack by id (e.g. `engineering`, `research`). Returns SpecialistPack (name, system_prompt, tools). Implemented by config-driven registry loading from `infrastructure.specialists`.

Config (model base URL, model name, timeouts, which specialists exist) is loaded at the interface layer and passed into use cases or infrastructure constructors; the application does not read env or files directly.

---

## 5. Flow: execute task (use case)

1. **Interfaces** (CLI or API): Parse prompt and options; load config; call `execute_task(prompt, specialist_id=None, model_key=..., workspace_root=..., network_allowed=...)`.
2. **Application** (`execute_task`):
   - Resolve specialist: if `specialist_id` given, use it; else **recruit** (today: keyword-based selection; later: capability-based). Result: one or more specialist ids (today: one).
   - For each specialist (today: one): get `SpecialistPack` (system prompt, tools) from SpecialistRegistry; create run via RunRepository; run **tool loop** until completion or max steps:
     - Build messages (system + user + prior turns); call **ChatClient.chat**; parse response (tool call or final answer); if tool call, call **ToolExecutor**, append tool result to messages, repeat; if final, persist and return run result.
   - Return aggregated result (run id, workspace path, run log path, final payload).
3. **Infrastructure**: Ollama client does HTTP to Ollama; RunRepository creates `.fabric/runs/<run_id>/` and `workspace/` and appends events to `runlog.jsonl`; ToolExecutor runs tools in sandbox and returns structured results.

Domain types (`Run`, `RunId`, `Task`, etc.) are used in the application and optionally in infrastructure; they contain no I/O.

---

## 6. What we do not carry over from the PoC

- **No** flat “supervisor”, “router”, “workflows/engineering_v1” as the main entry points. Replaced by application use case `execute_task` and clear recruit/orchestration (recruit module).
- **No** “workflows” as separate per-pack loops with duplicated JSON-parsing and tool-dispatch logic. Replaced by one **tool loop** in the application, parameterised by specialist pack (system prompt + tools).
- **No** ad-hoc “run_task” in a module that also creates run dirs and knows about LLM client. Replaced by ExecuteTask use case that depends on ports; run dir and LLM are behind RunRepository and ChatClient.
- **No** config and “router” mixed with execution. Config is loaded at the edge; recruit (router) is a clear step that returns specialist id(s); execution uses only those ids and config passed in.
- **No** `_v1` or “v1” in public names. Specialist packs are named by domain (engineering, research); versions are internal if ever needed.

---

## 7. Phasing the rebuild

1. **Phase A (skeleton)** — Create the package layout above; domain models and errors; ports (interfaces); config schema and loader. Implement minimal ExecuteTask (single specialist, keyword recruit) and one specialist pack (engineering) with tool loop; Ollama client and file-based run log; CLI and API that call `execute_task`. No dependency on prototype code; design is from first principles (see docs/DESIGN.md).
2. **Phase B** — Add research specialist; harden tool loop (retries, better JSON handling); run log and run directory fully behind RunRepository.
3. **Phase C** — Capability model and recruit from capabilities (still single specialist per run); then multi-specialist task force if needed.

Tests: unit tests for domain and application (mocked ports); integration tests for infrastructure (Ollama client against real Ollama or mock server; run directory and run log on disk). No tests that depend on the old prototype structure.

---

## 8. File and module naming summary

| Area | Naming | Example |
|------|--------|--------|
| Domain entities | PascalCase, noun | `Run`, `RunId`, `Task`, `Capability` |
| Application use cases | snake_case, verb | `execute_task`, `recruit_specialists` |
| Ports (interfaces) | PascalCase, role | `ChatClient`, `RunRepository`, `ToolExecutor` |
| Infrastructure adapters | PascalCase, concrete | `OllamaChatClient`, `FileSystemRunRepository` |
| Modules | snake_case | `execute_task.py`, `run_log.py`, `ollama/client.py` |
| Config | PascalCase for schema | `FabricConfig`, `ModelConfig` |

See **ENGINEERING.md** for full coding standards and practices.
