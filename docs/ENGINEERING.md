# Engineering standards and practices

We build agentic-concierge from the ground up with consistent naming, clear organisation, and testability. Follow these standards for all new code.

---

## 1. Naming conventions

### 1.1 Modules and packages

- **Packages:** `snake_case` directory names (e.g. `run_directory`, `ollama`). One package per bounded area.
- **Modules:** `snake_case` filenames; one primary concept per file (e.g. `execute_task.py`, `run_log.py`, `ollama/client.py`).
- **No** version suffixes in public names: use `engineering.py` not `engineering_v1.py`. Version internally if needed (e.g. `_ENGINEERING_SCHEMA_V1`).

### 1.2 Classes and types

- **PascalCase** for all classes and typed dataclasses (e.g. `Run`, `RunId`, `OllamaChatClient`, `ConciergeConfig`).
- **Domain entities** — nouns that match the ubiquitous language: `Task`, `Run`, `RunId`, `Capability`, `SpecialistId`, `ToolCall`, `ToolResult`.
- **Ports (interfaces)** — role names: `ChatClient`, `RunRepository`, `ToolExecutor`, `SpecialistRegistry`.
- **Infrastructure** — concrete adapter names: `OllamaChatClient`, `FileSystemRunRepository`.

### 1.3 Functions and methods

- **snake_case** for functions and methods (e.g. `execute_task`, `load_config`, `append_event`).
- **Use-case entry points** — verb phrases: `execute_task`, `recruit_specialists`.
- **Private (module- or class-local)** — leading underscore: `_parse_tool_response`, `_default_config`.

### 1.4 Constants and config keys

- **True constants:** `UPPER_SNAKE` (e.g. `MAX_TOOL_LOOP_STEPS = 50`).
- **Config keys** — match schema field names (snake_case in JSON/YAML); Pydantic model fields are snake_case.

### 1.5 Variables and parameters

- **snake_case** for variables and function parameters (e.g. `run_id`, `workspace_root`, `model_key`).
- Descriptive names: `run_dir` not `d`, `specialist_id` not `sid` (except very short scope).

---

## 2. Code organisation

- **One clear responsibility per module.** If a file grows beyond a single concern, split it (e.g. `run_directory.py` for creating run dirs, `run_log.py` for appending events).
- **Domain** — No imports from application, infrastructure, or interfaces. No I/O, no HTTP, no file paths that touch the real FS (value objects only).
- **Application** — Imports domain and **ports** (abstract interfaces). No direct imports of infrastructure adapters; adapters are injected or wired at the interface layer.
- **Infrastructure** — Implements ports; may import domain types (e.g. `RunId`) and config types. No business logic beyond “how to do I/O”.
- **Interfaces** — Wire config, infrastructure, and application; parse input and format output only.

---

## 3. Dependency rule

- **Domain** ← **Application** ← **Infrastructure** and **Interfaces**.
- Application must not depend on Infrastructure or Interfaces. Pass in dependencies (e.g. `ExecuteTask(run_repo=..., chat_client=..., tool_executor=...)`) or use a thin composition root in Interfaces that builds adapters and calls the use case.

---

## 4. Testing

- **Domain and application:** Unit tests with mocks/fakes for ports. No real Ollama or file system.
- **Infrastructure:** Integration tests (e.g. real run directory on disk, or mock HTTP server for Ollama).
- **Interfaces:** Optional; or test via application with fake adapters. E2E tests can call CLI/API with a real Ollama or mock.
- **Naming:** Test modules `test_<module>.py` or `tests/<area>/test_<feature>.py`; test functions `test_<behaviour>` (e.g. `test_execute_task_creates_run_directory`).

---

## 5. Error handling

- **Domain/application errors** — Define in `domain.errors` (e.g. `RecruitError`, `ToolExecutionError`). Use specific types; avoid bare `Exception` in signatures.
- **Infrastructure** — Translate external errors (e.g. HTTP, OS) into domain/application errors or re-raise with clear context.
- **Interfaces** — Map application errors to HTTP status codes or CLI exit codes and user-facing messages.

---

## 6. Documentation

- **Public modules:** Top-level docstring describing the module’s responsibility.
- **Public classes and use-case functions:** Docstring with purpose, parameters, return value, and raised errors.
- **Complex logic:** Inline comments for “why”, not “what”. Prefer clear names over comments.

---

## 7. What we avoid (from the PoC)

- No flat “god” modules (e.g. a single `supervisor.py` that does routing, run creation, and loop execution).
- No `_v1` or prototype-style suffixes in public API or file names.
- No business logic in infrastructure (e.g. “how to choose a specialist” belongs in application, not in a “router” module that also does I/O).
- No duplicated tool-loop or JSON-parsing logic across multiple “workflow” files; one tool loop in the application, parameterised by specialist.
