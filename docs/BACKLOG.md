# agent-fabric: Prioritised Backlog

**Purpose:** Single source of truth for *what to work on next, in what order, and why*.
Each item is self-contained: a fresh session can pick up any item using only this file, the
referenced source files, and [DECISIONS.md](DECISIONS.md).

**How to use this file**
- Items within each tier are ordered by priority (top = most urgent).
- When starting an item: add `**Status: IN PROGRESS — <date>**` to the item.
- When complete: move the item to the **Done** section; add `**Completed: <date>**`.
- New items go into the appropriate tier with full context written in at the time.
- Never leave an item as "IN PROGRESS" without updating STATE.md too.

**How to resume after an interruption**
1. Read [STATE.md](STATE.md) — confirms current phase and last verified state.
2. Read this file — find the first non-done item; that is what to work on.
3. Run `pytest tests/ -k "not real_llm and not verify and not real_mcp"` — confirm **368 pass** before touching code.
4. Start the item; mark it IN PROGRESS here and in STATE.md.

---

## Tier 1 — Fix before Phase 2 (correctness and robustness)

These items are defects or gaps that make the system incorrect or fragile in ways that will
compound as Phase 2 adds more complexity. Do these before adding any new Phase 2 work.

---

### ~~T1-1: Validate `finish_task` payload before returning it~~ **DONE 2026-02-24**

**Why:** The LLM can call `finish_task` with an empty or partial argument object. The current
code spreads `tc.arguments` directly into the payload (`{"action": "final", **tc.arguments}`)
with no validation. If `summary` is missing the result is silently malformed. Callers (HTTP API,
CLI) will return a payload that is missing required fields with no error surfaced to the user.

**What to change:**
- `src/agent_fabric/application/execute_task.py` — where `finish_payload` is set (around
  the `if tc.tool_name == pack.finish_tool_name` block):
  - Validate `tc.arguments` contains at minimum `"summary"`.
  - If validation fails: log a `tool_result` event with the error, send the error back to the
    LLM as a tool result (so it can retry), and do **not** set `finish_payload`.
- `src/agent_fabric/domain/errors.py` — add `FinishTaskValidationError` if needed.

**Acceptance criteria:**
- [ ] LLM calling `finish_task({})` causes the error to be returned to the LLM as a tool result,
      not silently accepted as a final payload.
- [ ] LLM calling `finish_task({"summary": "x"})` succeeds as before.
- [ ] New unit test in `tests/test_execute_task.py` (create this file) covering both cases.
- [ ] `pytest tests/ -k "not real_llm and not verify"` still passes (45+).

**Files:** `src/agent_fabric/application/execute_task.py`, `tests/test_execute_task.py` (new)

---

### ~~T1-2: Replace bare `except Exception` in tool execution~~ **DONE 2026-02-24**

**Why:** `execute_task.py` catches `except Exception` around tool execution. This swallows
`KeyboardInterrupt`, `SystemExit`, `MemoryError`, and other non-recoverable signals. More
importantly, it hides the *nature* of failures: a sandbox `PermissionError` (security event),
a `FileNotFoundError` (tool bug), and a `ValueError` (bad arguments) are all treated identically.

**What to change:**
- `src/agent_fabric/application/execute_task.py` — around `pack.execute_tool(...)`:
  - Catch specific exceptions: `PermissionError` (sandbox violation), `ValueError`/`TypeError`
    (bad args), `OSError` (filesystem), `Exception` as final fallback — but log each distinctly.
  - Add a `kind: "tool_error"` event to the runlog when a tool fails, distinct from a normal
    `tool_result`. Include `tool_name`, `error_type`, `error_message`.
  - Do NOT re-raise — the LLM should receive the error as a tool result so it can adapt.
- `src/agent_fabric/infrastructure/workspace/run_log.py` — add `log_tool_error()` if not present.

**Acceptance criteria:**
- [ ] A tool that raises `PermissionError` (sandbox escape) produces a `tool_error` runlog event.
- [ ] A tool that raises `ValueError` (bad args) produces a `tool_error` runlog event.
- [ ] `KeyboardInterrupt` propagates up normally (is not caught).
- [ ] Tests in `tests/test_execute_task.py` covering sandbox violation and bad-args paths.
- [ ] `pytest tests/ -k "not real_llm and not verify"` still passes.

**Files:** `src/agent_fabric/application/execute_task.py`,
`src/agent_fabric/infrastructure/workspace/run_log.py`, `tests/test_execute_task.py`

---

### ~~T1-3: Add structured logging (Python `logging` module)~~ **DONE 2026-02-24**

**Why:** There is currently no `logging` usage anywhere. Diagnosing failures in the HTTP API
or CLI requires inspecting `runlog.jsonl` files on disk. You cannot enable debug output,
cannot see what the server is doing at runtime, and cannot integrate with log aggregators.
This is below the bar for any system intended to run unattended.

**What to add:**
- Every module that has observable behaviour should log at appropriate levels:
  - **DEBUG:** LLM request/response payloads, tool arguments/results, step counter.
  - **INFO:** Task started/completed, model resolved, specialist recruited, run_id created.
  - **WARNING:** Fallback paths (minimal payload retry, plain-text LLM response), 400 errors.
  - **ERROR:** Unrecoverable errors (model not found, sandbox violation, config invalid).
- Use a single logger per module: `logger = logging.getLogger(__name__)`.
- In `interfaces/cli.py`: configure root logger at INFO or DEBUG based on `--verbose` flag.
- In `interfaces/http_api.py`: configure at startup (use uvicorn's existing logging config).
- Do NOT log sensitive data (API keys, file contents by default).

**Key files to instrument first (highest value):**
1. `src/agent_fabric/application/execute_task.py` — task start/end, each step, LLM fallback
2. `src/agent_fabric/infrastructure/ollama/client.py` — request sent, response received, retries
3. `src/agent_fabric/infrastructure/llm_discovery.py` — model resolved, fallbacks
4. `src/agent_fabric/interfaces/http_api.py` — request received, result returned
5. `src/agent_fabric/interfaces/cli.py` — add `--verbose` flag wiring

**Acceptance criteria:**
- [ ] `fabric run "list files" --pack engineering --verbose` prints INFO-level log lines to stderr.
- [ ] Running the HTTP server and hitting `POST /run` produces log output at INFO.
- [ ] No sensitive data (API keys) in default logs.
- [ ] No existing tests broken.
- [ ] Logging is silent by default in unit tests (configure `logging.NullHandler` at library root).

**Files:** Almost all `src/` modules. Start with execute_task, client, llm_discovery, interfaces.

---

### ~~T1-4: Make the specialist registry extensible (config-driven, not hardcoded)~~ **DONE 2026-02-24**

**Why:** `infrastructure/specialists/registry.py` has a hardcoded `_BUILDERS` dict. Every new
specialist pack requires editing core code. The vision explicitly expects new capability areas to
be added without architectural surgery. This also blocks Phase 2 which adds capability-based
routing — that feature is useless if packs can only be added by editing the registry.

**What to change:**
- `src/agent_fabric/infrastructure/specialists/registry.py` — replace the hardcoded dict with
  one of these two strategies (prefer A):
  - **Strategy A (recommended): Config-driven factory map.**
    `FabricConfig.specialists` already exists as `dict[str, SpecialistConfig]`. Extend
    `SpecialistConfig` with an optional `builder` field (dotted module path, e.g.
    `"agent_fabric.infrastructure.specialists.engineering:build_engineering_pack"`).
    The registry imports and calls the builder at `get_pack()` time.
    Built-in packs are registered via a default factory map keyed by `specialist_id`; config
    can override or add new ones.
  - **Strategy B: `importlib.metadata` entry points.**
    Define a `"agent_fabric.specialists"` entry point group. Built-in packs are registered in
    `pyproject.toml`; external packs can register themselves the same way.
    This is the most Pythonic plugin pattern but requires a bit more setup.
- Either strategy must preserve backward compatibility with existing tests and config.

**Acceptance criteria:**
- [ ] Adding a new specialist pack does NOT require editing `registry.py`.
- [ ] Existing `engineering` and `research` packs work as before.
- [ ] A test in `tests/test_specialist_registry.py` (new) demonstrates registering a minimal
      custom pack without modifying core code.
- [ ] `pytest tests/ -k "not real_llm and not verify"` still passes.

**Files:** `src/agent_fabric/infrastructure/specialists/registry.py`,
`src/agent_fabric/config/schema.py` (if Strategy A), `pyproject.toml` (if Strategy B),
`tests/test_specialist_registry.py` (new)

---

## Tier 2 — Important, not blocking (quality and maintainability)

Do these after all T1 items, or interleaved if a T1 item is blocked/waiting.

---

### ~~T2-1: Extract shared tool-definition helpers (DRY)~~ **DONE 2026-02-24**

**Why:** `_tool()` helper and the `finish_task` tool definition are duplicated between
`engineering.py` and `research.py`. They will diverge over time. Also blocks the extensibility
work (T1-4) because new packs will copy-paste the same boilerplate.

**What to change:**
- Create `src/agent_fabric/infrastructure/specialists/tool_defs.py` with:
  - `def make_tool_def(name, description, parameters, required=None) -> dict` — the `_tool()` helper.
  - `def make_finish_tool_def(description, extra_properties=None, extra_required=None) -> dict`
    — builds the finish_task definition with common base fields (summary, artifacts, next_steps,
    notes) plus any pack-specific extras.
- Update `engineering.py` and `research.py` to import from `tool_defs.py`.

**Acceptance criteria:**
- [ ] `_tool()` is not defined in either `engineering.py` or `research.py`.
- [ ] `finish_task` base schema (summary, artifacts, next_steps, notes) is defined once.
- [ ] All existing pack tests still pass.

**Files:** `src/agent_fabric/infrastructure/specialists/tool_defs.py` (new),
`engineering.py`, `research.py`

---

### ~~T2-2: Cache `load_config()` to avoid re-parsing on every HTTP request~~ **DONE 2026-02-24**

**Why:** `http_api.py` calls `load_config()` on every `POST /run`. The function reads the file
from disk, parses JSON, and constructs a Pydantic model — every single time. This is a silent
per-request cost that will matter at any reasonable call rate.

**What to change:**
- `src/agent_fabric/config/loader.py` — use `functools.lru_cache` with `maxsize=1` on
  `load_config()` OR cache the result at module level with a `_cache: FabricConfig | None`.
  - The cache must be invalidatable in tests (use `load_config.cache_clear()` if lru_cache).
  - Config should be reloaded if `FABRIC_CONFIG_PATH` changes (accept this limitation for now;
    document it).
- `src/agent_fabric/interfaces/http_api.py` — no changes needed if caching is in loader.

**Acceptance criteria:**
- [ ] `load_config()` only reads the filesystem once per process (subsequent calls return cached).
- [ ] Tests can reset cache between test runs (via `cache_clear()` or module-level reset).
- [ ] No existing tests broken.

**Files:** `src/agent_fabric/config/loader.py`

---

### ~~T2-3: Expand test coverage for error paths in `execute_task`~~ **DONE 2026-02-24**

**Why:** The error paths in the tool loop are entirely untested:
- LLM returns plain text (no tool calls) — code at execute_task.py lines ~106-117
- `max_steps` exhausted — code at execute_task.py lines ~163-171
- Tool raises an exception — covered by T1-2 but needs tests written
- LLM returns malformed tool arguments (`{"_raw": "..."}` fallback in client.py)

Without these tests, regressions in error handling will go undetected.

**What to add:** `tests/test_execute_task.py` (started in T1-1 and T1-2):
- `test_plain_text_response_is_final_payload` — mock LLM returns `LLMResponse(content="done", tool_calls=[])`.
- `test_max_steps_exceeded_produces_timeout_payload` — mock LLM always returns a non-finish tool call.
- `test_tool_exception_is_returned_to_llm` — mock tool raises `ValueError`; next LLM call should see error in messages.
- `test_malformed_tool_arguments_logged` — mock LLM returns `tool_calls` with `arguments="{not json}"`.

**Acceptance criteria:**
- [ ] All 4 tests above are implemented and pass.
- [ ] `pytest tests/ -k "not real_llm and not verify"` passes (49+ tests).

**Files:** `tests/test_execute_task.py`

---

### ~~T2-4: Log sandbox violations as security events (audit trail)~~ **DONE 2026-02-24**

**Why:** When a tool call tries to escape the sandbox (`PermissionError` from `safe_path()`),
this is currently silently returned as `{"error": "..."}` in the tool result with no
distinguishing mark. There is no audit trail that a potentially adversarial input attempted
a path escape. For any system running LLM-generated code, this is a meaningful security gap.

**What to change:**
- `src/agent_fabric/application/execute_task.py` — in the scoped exception handler (T1-2):
  when the caught exception is `PermissionError`, write a `kind: "security_event"` entry to
  the runlog in addition to the `tool_error` entry.
- `src/agent_fabric/infrastructure/workspace/run_log.py` — add `log_security_event()`.

**Acceptance criteria:**
- [ ] A `PermissionError` from tool execution produces a `security_event` runlog entry with
      `tool_name`, `error_message`, and `timestamp`.
- [ ] Test in `tests/test_execute_task.py`.

**Files:** `execute_task.py`, `run_log.py`, `tests/test_execute_task.py`

---

### ~~T2-5: Document and centralise magic numbers~~ **DONE 2026-02-24**

**Why:** `50_000` (output truncation in sandbox), `2000` (content truncation in execute_task),
`10.0` / `120.0` / `360.0` (various timeouts) are scattered through the code with no
explanation. Future maintainers cannot tell whether these are safe to change.

**What to change:**
- `src/agent_fabric/config/schema.py` or a new `src/agent_fabric/config/constants.py`:
  - `MAX_TOOL_OUTPUT_CHARS: int = 50_000` — explain: prevents OOM from runaway shell output.
  - `MAX_LLM_CONTENT_IN_RUNLOG_CHARS: int = 2_000` — explain: runlog size control.
  - `LLM_DISCOVERY_TIMEOUT_S: float = 10.0` — explain: fast check, don't block startup.
  - `LLM_CHAT_DEFAULT_TIMEOUT_S: float = 120.0` — explain: single generation step.
- Update all references to use these constants.
- Add a comment on each explaining the rationale.

**Acceptance criteria:**
- [ ] No bare numeric literals for the above values; all use named constants.
- [ ] Each constant has a docstring or comment explaining its purpose and rationale.
- [ ] All existing tests still pass.

**Files:** `config/constants.py` (new), `sandbox.py`, `execute_task.py`, `client.py`,
`llm_discovery.py`

---

## Tier 3 — Nice to have (polish and developer experience)

Do after T1 and T2, or pick up opportunistically when adjacent work is in progress.

---

### ~~T3-1: Add architecture diagram~~ **DONE 2026-02-24**

A single ASCII or Mermaid diagram in `docs/ARCHITECTURE.md` showing the layer boundaries,
key classes, and data flow (task in → LLM loop → result out). Invaluable for onboarding
new contributors and for reasoning about Phase 2 changes.

### ~~T3-2: Parametrize tests where multiple scenarios are similar~~ **DONE 2026-02-24**

`tests/test_packs.py` and `tests/test_router.py` repeat similar structures. Use
`@pytest.mark.parametrize` to reduce duplication and cover more cases with less code.

### ~~T3-3: Tie-breaking and documentation in `recruit.py`~~ **DONE 2026-02-24**

Current max() on keyword scores has undefined tie-breaking behaviour (Python dict ordering).
Document this; add a deterministic tie-break (e.g., config order) and a test for it.

### ~~T3-4: Validate specialist IDs at config load time~~ **DONE 2026-02-24**

Config can reference a `specialist_id` that doesn't exist in `config.specialists`. This only
fails at execution time (when `get_pack()` raises). Add a validator in `FabricConfig` that
ensures every specialist referenced in routes/defaults exists in `config.specialists`.

### ~~T3-5: Extract `Task` construction to shared helper~~ **DONE 2026-02-24**

CLI (`cli.py:63`) and HTTP API (`http_api.py:59-64`) both construct `Task(...)` with identical
field mapping. Extract to `_build_task(prompt, pack, model_key, network_allowed) -> Task` in
a shared module (e.g., `application/task_factory.py` or directly in `domain`).

---

## Phase 2 items (next phase, not started)

These are the Phase 2 deliverables from [PLAN.md](PLAN.md). Do not start these until all T1
items are done and the Phase 1 verification gate still passes.

---

### ~~P2-1: Capability model — define capabilities and map packs~~ **DONE 2026-02-24**

**What:** Define a set of capability IDs (e.g., `"code_execution"`, `"file_io"`,
`"systematic_review"`, `"web_search"`) and declare which capabilities each pack provides
in `FabricConfig.specialists[id].capabilities: list[str]`.

**Why:** Enables task→capabilities→pack routing that is grounded in what packs can actually do,
not keyword heuristics.

**Files:** `src/agent_fabric/config/schema.py`, `docs/CAPABILITIES.md` (new)

---

### ~~P2-2: Task-to-capabilities mapping~~ **DONE 2026-02-24**

**What:** Given a task prompt, determine the required capability IDs. Start with a rules/keyword
approach (similar to current routing but keyed to capability IDs, not pack names). Later replace
with a small router model + JSON schema.

**Why:** Decouples "what capability is needed" from "which pack provides it" — enabling multi-pack
task forces in Phase 3.

**Files:** `src/agent_fabric/application/recruit.py` (rewrite or extend)

---

### ~~P2-3: Recruit pack from capabilities~~ **DONE 2026-02-24**

**What:** Select the pack(s) whose declared capabilities cover the required capabilities.
For Phase 2: still single pack per run. Log `required_capabilities` and `selected_pack` in
run metadata.

**Files:** `src/agent_fabric/application/recruit.py`, `execute_task.py`, `run_log.py`

---

### ~~P2-4: Log required capabilities and selected pack in run metadata~~ **DONE 2026-02-24**

**What:** `runlog.jsonl` and/or the `RunResult` metadata (`_meta` in HTTP response) should
include `required_capabilities: [...]` and `selected_pack: "..."`. This makes routing
decisions observable and debuggable.

**Files:** `execute_task.py`, `run_log.py`, `http_api.py`

---

### ~~P2-5: Update docs for Phase 2~~ **DONE 2026-02-24**

**What:** Update `STATE.md` (Phase 2 complete), `PLAN.md` (tick off deliverables), `VISION.md §8`
(alignment table), and `REQUIREMENTS.md` (describe capability-based routing as a functional
requirement).

---

## Phase 3 items (multi-pack task force) — **complete**

---

### ~~P3-1: Multi-pack recruitment (RecruitmentResult.specialist_ids)~~ **DONE 2026-02-24**

**What:** Changed `RecruitmentResult` from a single `specialist_id: str` to
`specialist_ids: List[str]` with `specialist_id` as a backward-compatible property.
Added `is_task_force` property. Added `_greedy_select_specialists()` to pick the
minimum set of specialists that covers all required capabilities.

**Files:** `src/agent_fabric/application/recruit.py`

---

### ~~P3-2: Multi-pack execute_task (sequential execution, shared runlog)~~ **DONE 2026-02-24**

**What:** Extracted `_execute_pack_loop()` from `execute_task()`. `execute_task` now
loops over `specialist_ids`, running each pack in turn. Logs `pack_start` events for
multi-pack runs; step names are prefixed with specialist ID (`engineering_step_0`,
`research_step_0`) so the runlog clearly shows which pack each step belongs to.

**Files:** `src/agent_fabric/application/execute_task.py`

---

### ~~P3-3: Context handoff and domain/HTTP updates~~ **DONE 2026-02-24**

**What:** Each subsequent pack receives the previous pack's `finish_task` payload as
context in its user message. Added `specialist_ids: List[str]` and `is_task_force`
property to `RunResult`. Updated `http_api.py` `_meta` to include `specialist_ids`
and `is_task_force`.

**Files:** `src/agent_fabric/domain/models.py`, `src/agent_fabric/interfaces/http_api.py`

---

### ~~P3-4: Tests for Phase 3~~ **DONE 2026-02-24**

**What:** Updated `test_capabilities.py` — replaced `test_mixed_prompt_routes_to_best_coverage`
with `test_mixed_prompt_routes_to_task_force` and added two more task-force specific tests.
New `tests/test_task_force.py` with 17 tests covering greedy selection, multi-pack recruitment,
sequential execution, runlog structure, context handoff, and `RunResult` properties.
Fast CI: **144 pass** (+22).

**Files:** `tests/test_capabilities.py`, `tests/test_task_force.py` (new)

---

### ~~P3-5: Docs and STATE updated for Phase 3~~ **DONE 2026-02-24**

**What:** BACKLOG.md Phase 3 section; STATE.md phase and CI count updated;
PLAN.md Phase 3 deliverables ticked off.

---

## Phase 4 items (observability and multi-backend LLM) — **complete**

---

### ~~P4-1: Generic/cloud LLM client + `ModelConfig.backend` field~~ **DONE 2026-02-24**

**What:** Added `backend: str = "ollama"` to `ModelConfig`. Created `infrastructure/chat/__init__.py` with `build_chat_client()` factory (dispatches on `backend`). Created `GenericChatClient` in `infrastructure/chat/generic.py` — bare OpenAI-compatible client, no Ollama 400 retry, raises immediately on non-2xx. Extracted shared `parse_chat_response()` into `infrastructure/chat/_parser.py`. Both `OllamaChatClient` and `GenericChatClient` import the shared parser. CLI and HTTP API now use `build_chat_client(resolved.model_config)` instead of hardcoded `OllamaChatClient`.

**Tests:** `tests/test_generic_client.py` — 15 tests.

---

### ~~P4-2: `fabric logs` CLI subcommand~~ **DONE 2026-02-24**

**What:** Added `fabric logs list` (Rich table of runs, sorted most-recent-first, respects `--limit`) and `fabric logs show <run_id>` (pretty-printed JSON events, optional `--kinds` filter) to `interfaces/cli.py`. Created `infrastructure/workspace/run_reader.py` with `RunSummary` dataclass, `list_runs()`, `read_run_events()`, `_parse_runlog()`, `_summarise_run()`. Silently skips malformed runlog lines.

**Tests:** `tests/test_logs_cli.py` — 18 tests.

---

### ~~P4-3: OpenTelemetry tracing (optional dep)~~ **DONE 2026-02-24**

**What:** Created `infrastructure/telemetry.py` with `_NoOpSpan`, `_NoOpTracer`, `setup_telemetry()`, `get_tracer()`, `reset_for_testing()`. Graceful no-op when `opentelemetry-sdk` is not installed. Added `TelemetryConfig` to `config/schema.py` (`enabled`, `service_name`, `exporter`, `otlp_endpoint`; supports `"none"` | `"console"` | `"otlp"`). Added `telemetry: Optional[TelemetryConfig]` to `FabricConfig`. Instrumented `execute_task.py` with `fabric.execute_task` (root span), `fabric.llm_call` (wraps `chat_client.chat()`), and `fabric.tool_call` (wraps `pack.execute_tool()`). Added `[otel]` optional dep to `pyproject.toml`. Wired `setup_telemetry()` into CLI `run` command and HTTP API `lifespan`.

**Tests:** `tests/test_telemetry.py` — 13 tests (no-op shim, OTEL-only span emission with `InMemorySpanExporter`, `TelemetryConfig` schema).

---

### ~~P4-4: Docs update for Phase 4~~ **DONE 2026-02-24**

**What:** Updated BACKLOG.md (this section), STATE.md (phase → Phase 4 complete, CI count → 194), PLAN.md (concrete Phase 4 deliverables + acceptance criteria).

---

## Phase 5 items (MCP tool server support) — **complete**

---

### ~~P5-1: Config schema — MCPServerConfig + mcp_servers~~ **DONE 2026-02-24**

**What:** Added `MCPServerConfig(BaseModel)` to `config/schema.py` (`name`, `transport`, `command`/`args`/`env` for stdio, `url`/`headers` for SSE, `timeout_s`; validators require `command` for stdio and `url` for SSE). Added `mcp_servers: List[MCPServerConfig]` to `SpecialistConfig` with a validator that rejects duplicate server names. +6 tests in `tests/test_config.py`.

**Files:** `src/agent_fabric/config/schema.py`, `tests/test_config.py`

---

### ~~P5-2: Async execute_tool + pack lifecycle~~ **DONE 2026-02-24**

**What:** Made `BaseSpecialistPack.execute_tool()` async (calls sync tool functions directly — no executor needed). Added no-op `aopen()`/`aclose()` to `BaseSpecialistPack`. Updated `SpecialistPack` Protocol (`execute_tool` async, `aopen`/`aclose` added). Updated `_execute_pack_loop` to `await pack.execute_tool(...)` and wrap the step loop in `try/finally: await pack.aopen() / await pack.aclose()`. Updated `_StubPack.execute_tool` in `tests/test_specialist_registry.py`.

**Files:** `src/agent_fabric/infrastructure/specialists/base.py`, `src/agent_fabric/application/ports.py`, `src/agent_fabric/application/execute_task.py`, `tests/test_specialist_registry.py`

---

### ~~P5-3: MCPSessionManager + converter~~ **DONE 2026-02-24**

**What:** Created `infrastructure/mcp/` package. `converter.py`: `mcp_tool_to_openai_def(prefixed_name, tool)` — substitutes empty schema when `inputSchema` is None. `session.py`: `MCPSessionManager` with `connect()`/`disconnect()` via `AsyncExitStack`, `list_tools()` returning prefixed OpenAI defs, `call_tool()` (strips prefix, returns `{"result": text}` or `{"error": text}`), `owns_tool()`. Top-level `mcp` imports guarded with try/except for graceful no-op when package absent. +12 tests in `tests/test_mcp_session.py` (all mocked).

**Files:** `src/agent_fabric/infrastructure/mcp/__init__.py`, `session.py`, `converter.py`; `tests/test_mcp_session.py` (new)

---

### ~~P5-4: MCPAugmentedPack~~ **DONE 2026-02-24**

**What:** Created `infrastructure/mcp/augmented_pack.py` with `MCPAugmentedPack(inner, sessions)`: `aopen()` — `asyncio.gather()` connects + populates `_mcp_tool_defs`; `aclose()` — `asyncio.gather(..., return_exceptions=True)` ignores individual failures; `tool_definitions` — inner + MCP tools; `execute_tool()` — dispatches to owning session or inner pack; forwards `specialist_id`, `system_prompt`, `finish_tool_name`, `finish_required_fields`. +10 tests in `tests/test_mcp_augmented_pack.py`.

**Files:** `src/agent_fabric/infrastructure/mcp/augmented_pack.py` (new); `tests/test_mcp_augmented_pack.py` (new)

---

### ~~P5-5: Registry integration~~ **DONE 2026-02-24**

**What:** Updated `ConfigSpecialistRegistry.get_pack()` to wrap the built pack with `MCPAugmentedPack` when `spec_cfg.mcp_servers` is non-empty. Import is guarded: raises `RuntimeError("mcp package not installed")` if `agent_fabric.infrastructure.mcp` cannot be imported. +6 tests in `tests/test_mcp_registry.py`.

**Files:** `src/agent_fabric/infrastructure/specialists/registry.py`, `tests/test_mcp_registry.py` (new)

---

### ~~P5-6: pyproject.toml + docs~~ **DONE 2026-02-24**

**What:** Added `mcp = ["mcp>=1.0"]` to `[project.optional-dependencies]`; also added `mcp>=1.0` to `dev` so CI tests can mock it. Updated BACKLOG.md (this section), STATE.md (phase → Phase 5 complete, CI count → ~242), PLAN.md (Phase 5 concrete deliverables).

**Files:** `pyproject.toml`, `docs/BACKLOG.md`, `docs/STATE.md`, `docs/PLAN.md`

---

## Phase 8 items — **complete**

Phase 7 is complete (P7-1 through P7-4 all done; fast CI: 342 pass). Phase 8 focused on concurrency (parallel task forces), real-time streaming, and run status observability. All P8-1 through P8-4 done; fast CI: **368 pass**.

---

### ~~P8-1: Parallel task force execution~~ **DONE 2026-02-25**

- `config/schema.py`: Added `task_force_mode: str = Field("sequential", ...)` to `FabricConfig`.
- `execute_task.py`: `_run_task_force_parallel()` + `_merge_parallel_payloads()`; parallel path via `asyncio.gather`; sequential is default/unchanged.
- 14 tests in `tests/test_parallel_task_force.py`.

---

### ~~P8-2: SSE run event streaming (HTTP API)~~ **DONE 2026-02-25**

- `execute_task.py`: `event_queue: Optional[asyncio.Queue]` param; `_emit()` helper; all events mirrored to queue; `run_complete` + `_run_done_` sentinels.
- `interfaces/http_api.py`: `POST /run/stream` returns `text/event-stream`; background asyncio task.
- 6 tests in `tests/test_run_streaming.py`.

---

### ~~P8-3: Run status endpoint~~ **DONE 2026-02-25**

- `interfaces/http_api.py`: `GET /runs/{run_id}/status` — reads runlog; returns `completed/running`; 404 if not found.
- 6 tests in `tests/test_run_status.py`.

---

### ~~P8-4: Docs update for Phase 8~~ **DONE 2026-02-25**

- STATE.md, BACKLOG.md, PLAN.md updated.

---

## Phase 7 items (next)

Phase 6 is complete (P6-1 through P6-4 all done; fast CI: 304 pass). Phase 7 focuses on upgrading the run index to semantic search, first real enterprise MCP integration (GitHub), and a dedicated enterprise research specialist. Work on P7-1 first.

---

### ~~P7-1: Semantic run index search (vector embeddings via Ollama)~~ **DONE 2026-02-25**

**Why:** P6-1 added keyword/substring matching for the run index. This is limited: "authentication" won't find runs about "login flow" or "OAuth". The vision requires "cross-run memory" that understands semantics. Vector embeddings give us semantic similarity search without any external cloud service — just the local Ollama embedding endpoint.

**What to build:**
- Extend `infrastructure/workspace/run_index.py`:
  - `RunIndexEntry` gets an optional `embedding: Optional[list[float]]` field.
  - New `embed_text(text: str, model: str, base_url: str) -> list[float]` async function — calls `POST /api/embeddings` on the Ollama endpoint.
  - New `semantic_search_index(query: str, workspace_root: str, config: FabricConfig, top_k: int = 10) -> list[RunIndexEntry]` — embeds the query, loads all entries, computes cosine similarity, returns top-k. Falls back to `search_index()` keyword search when no entries have embeddings.
  - `append_to_index()` updated to optionally embed the entry at write time (new `embed: bool` param; default False for backward compatibility — can opt in via config).
- `config/schema.py`: Add `RunIndexConfig(BaseModel)` with `embedding_model: Optional[str] = None` (e.g. `"nomic-embed-text"`). Add `run_index: RunIndexConfig = Field(default_factory=RunIndexConfig)` to `FabricConfig`.
- `execute_task.py`: Pass `config.run_index` to `append_to_index()` — embed when `embedding_model` is set.
- `interfaces/cli.py`: `fabric logs search` uses `semantic_search_index()` when embeddings are available; falls back to keyword search otherwise.

**Acceptance criteria:**
- [ ] `RunIndexEntry` can serialise/deserialise with `embedding` field (None = not embedded).
- [ ] `embed_text()` calls `POST /api/embeddings` and returns a float list; gracefully raises on HTTP error.
- [ ] `semantic_search_index()` ranks entries by cosine similarity to query embedding; falls back to keyword when no embeddings exist.
- [ ] Existing `search_index()` still works unchanged (backward compat).
- [ ] `RunIndexConfig(embedding_model="nomic-embed-text")` in config → `execute_task` embeds each run; absent/None → no embedding (unchanged behaviour).
- [ ] Tests: `tests/test_run_index_semantic.py` — 10–12 tests; all mocked (no real Ollama needed for fast CI). Fast CI stays green.

**Files:** `infrastructure/workspace/run_index.py`, `config/schema.py`, `application/execute_task.py`, `interfaces/cli.py`, `tests/test_run_index_semantic.py` (new)

---

### ~~P7-2: GitHub MCP integration + real tests~~ **DONE 2026-02-25**

**Why:** Phase 5 built the MCP infrastructure; P6-2 verified it with a filesystem server. The most immediately useful enterprise integration is GitHub — searching issues, PRs, code, and commit history. The `@modelcontextprotocol/server-github` package is the official MCP server.

**What to build:**
- `MCPServerConfig.env` already exists for auth tokens. No new config fields needed.
- Add a `github_search` capability ID to `config/capabilities.py` (`CAPABILITY_KEYWORDS`).
- `tests/test_mcp_real_github.py` (new, `@pytest.mark.real_mcp`):
  - Fixture `skip_if_github_token_missing` — skips when `GITHUB_TOKEN` env var is absent.
  - Fixture `github_mcp_config` — returns `MCPServerConfig(name="github", transport="stdio", command="npx", args=["@modelcontextprotocol/server-github"], env={"GITHUB_TOKEN": os.environ["GITHUB_TOKEN"]})`.
  - 4 tests: `test_list_tools_returns_non_empty`, `test_search_repositories`, `test_get_file_contents`, `test_unknown_tool_returns_error`.
- Add a config example in `docs/MCP_INTEGRATIONS.md` (new) showing how to wire the GitHub server into an `enterprise_research` specialist.

**Acceptance criteria:**
- [ ] `tests/test_mcp_real_github.py` passes when `GITHUB_TOKEN` is set and `npx` is in PATH.
- [ ] Tests are deselected from fast CI (`-k "not real_mcp"`).
- [ ] `docs/MCP_INTEGRATIONS.md` includes complete `FabricConfig` YAML examples for GitHub, Confluence, and Jira stubs (even if Confluence/Jira tests are deferred).
- [ ] Fast CI count unchanged.

**Files:** `tests/test_mcp_real_github.py` (new), `config/capabilities.py`, `docs/MCP_INTEGRATIONS.md` (new)

---

### ~~P7-3: Enterprise research specialist~~ **DONE 2026-02-25**

**Why:** §4.3 of the vision describes an enterprise research assistant that searches Confluence, GitHub, Jira, and Rally and produces reports with staleness and confidence notes. We now have all the infrastructure (MCP, multi-pack, run index). The missing piece is a specialist pack designed for this use case.

**What to build:**
- `infrastructure/specialists/enterprise_research.py` (new):
  - `build_enterprise_research_pack(cfg: SpecialistConfig) -> SpecialistPack`
  - System prompt: enterprise research mode — search across MCP-backed sources (GitHub, Confluence, Jira), produce structured report with links, confidence notes, and explicit staleness caveats.
  - Tools: all research tools + a `cross_run_search` tool that calls `semantic_search_index()` to retrieve relevant prior run summaries.
  - `specialist_id = "enterprise_research"`, `capabilities = ["enterprise_search", "systematic_review", "web_search"]`
- `config/capabilities.py`: Add `"enterprise_search"` to `CAPABILITY_KEYWORDS` with relevant keywords (`confluence`, `jira`, `github issue`, `enterprise`, `knowledge base`, `internal docs`).
- Default config: add `enterprise_research` specialist entry (with `mcp_servers: []` as placeholder; comment explaining how to add GitHub/Confluence servers).
- `tests/test_enterprise_research_pack.py` (new): 10 tests — system prompt content, capability declaration, `cross_run_search` tool definition, tool dispatch to inner pack or index search, `finish_task` definition.

**Acceptance criteria:**
- [ ] `infer_capabilities("search confluence for supply management policies")` returns `["enterprise_search"]`.
- [ ] `recruit_specialist(task)` selects `enterprise_research` for enterprise-search prompts.
- [ ] `cross_run_search` tool calls `semantic_search_index()` (or `search_index()` fallback).
- [ ] Tests: 10+ pass; fast CI stays green.

**Files:** `infrastructure/specialists/enterprise_research.py` (new), `config/capabilities.py`, default config, `tests/test_enterprise_research_pack.py` (new)

---

### ~~P7-4: Docs update for Phase 7~~ **DONE 2026-02-25**

**What:** Update STATE.md (phase → Phase 7 complete, CI count), PLAN.md (Phase 7 deliverables ticked off), VISION.md §7+§8 (Phase 7 in history; enterprise integrations row updated), BACKLOG.md done table.

---

## Phase 6 items (complete)

---

### ~~P6-1: Persistent cross-run memory (run index + summary store)~~ **DONE 2026-02-24**

**Why:** Every run is currently a black box — the fabric cannot build on previous work, refer to past findings, or avoid repeating itself across conversations or tasks. The vision describes an enterprise assistant that accumulates context. Without memory, each task starts cold.

**What to build:**
- A `RunIndex` infrastructure component that maintains a lightweight JSONL index of all past runs: `run_id`, `specialist_ids`, `prompt_prefix` (first 200 chars), `finish_summary` (from `payload["summary"]`), `timestamp`, `workspace_path`.
- Index is written atomically after each successful run (append to `.fabric/run_index.jsonl`).
- A `search_runs(query: str) -> list[RunSummary]` function (keyword / substring, no vector store yet) that lets a future pack or the orchestrator retrieve relevant prior results.
- Expose via `fabric logs search <query>` CLI subcommand.
- Phase 6.2 will add vector search; Phase 6.1 uses substring matching — simple, no new deps.

**Acceptance criteria:**
- [ ] Every `execute_task` run appends to the run index on success.
- [ ] `fabric logs search "kubernetes"` returns all prior runs whose prompt or summary contains that string.
- [ ] The index file is append-only JSONL; survives partial writes (write + atomic rename).
- [ ] Tests: `tests/test_run_index.py` — 8–10 tests; fast CI stays green.

**Files:** `infrastructure/workspace/run_index.py` (new), `interfaces/cli.py`, `application/execute_task.py`

---

### ~~P6-2: Real MCP server smoke test (filesystem server)~~ **DONE 2026-02-25**

**Why:** Phase 5 built all the MCP wiring but every test mocks the transport layer. We have never run a real MCP server end-to-end through the fabric. The `mcp` package is installed in dev but its integration with a real subprocess has never been verified.

**What to build:**
- A `tests/test_mcp_real_server.py` marked `@pytest.mark.real_mcp` (like `real_llm`) — deselected from fast CI but runnable with `-k real_mcp`.
- Uses the official `@modelcontextprotocol/server-filesystem` npm package (must be installed: `npm install -g @modelcontextprotocol/server-filesystem`) with a tmp directory as root.
- Test: connect `MCPSessionManager`, call `list_tools()`, call `read_file` (or equivalent), assert result dict contains `"result"`.
- A fixture `skip_if_npx_unavailable` that skips gracefully if `npx` is not in PATH.

**What was built:**
- `tests/test_mcp_real_server.py`: 5 tests (`test_list_tools_returns_non_empty`, `test_owns_tool_prefix`, `test_read_file_via_call_tool`, `test_unknown_tool_returns_error`, `test_reconnect_after_disconnect`). Two fixtures: `skip_if_npx_unavailable` (checks `npx` in PATH + probes package), `skip_if_mcp_not_installed` (skips if `mcp` Python package absent). All 5 pass against real `@modelcontextprotocol/server-filesystem` server.
- `pyproject.toml`: Added `[tool.pytest.ini_options] markers` with `real_llm` and `real_mcp` entries.
- Fast CI: 257 pass (unchanged).

**Files:** `tests/test_mcp_real_server.py` (new), `pyproject.toml` (add `real_mcp` marker)

---

### ~~P6-3: Containerised workspace isolation (Podman)~~ **DONE 2026-02-25**

**Why:** The engineering pack runs shell commands in a shared workspace directory. There is no OS-level isolation — a rogue LLM call can reach the host filesystem beyond the workspace. The vision explicitly calls for Podman-based containment for specialist workers.

**What to build:**
- A `ContainerisedSpecialistPack` wrapper (similar to `MCPAugmentedPack`) that:
  - On `aopen()`: starts a Podman container from a base image (configurable), mounts the workspace as `/workspace`.
  - Overrides the `shell` tool to forward commands into `podman exec` rather than `subprocess.run` locally.
  - On `aclose()`: stops and removes the container.
- `SpecialistConfig.container_image: Optional[str]` — when set, the registry wraps with `ContainerisedSpecialistPack`.
- Default: no container (existing behaviour unchanged).

**What was built:**
- `infrastructure/specialists/containerised.py`: `ContainerisedSpecialistPack` — starts `podman run -d --rm -v workspace:/workspace:Z image sleep infinity` on `aopen()`, runs shell via `podman exec -w /workspace`, stops container on `aclose()`. Applies command allowlist for defence-in-depth. `:Z` volume option for SELinux hosts (Fedora/RHEL). Calls `inner.aopen()`/`inner.aclose()` to propagate lifecycle to MCP sessions.
- `config/schema.py`: `container_image: Optional[str]` field on `SpecialistConfig`.
- `registry.py`: Wraps with `ContainerisedSpecialistPack` after MCP wrap when `container_image` is set.
- `pyproject.toml`: Added `podman` marker.
- `tests/test_containerised_pack.py`: 26 tests — 22 unit (mocked subprocess) + 4 `@pytest.mark.podman` integration (run against real python:3.11-slim; all pass).
- Fast CI: 283 pass (+26).

**Files:** `infrastructure/specialists/containerised.py` (new), `config/schema.py`, `infrastructure/specialists/registry.py`, `pyproject.toml`, `tests/test_containerised_pack.py` (new)

---

### ~~P6-4: Cloud LLM fallback (quality/capability gate)~~ **DONE 2026-02-25**

**Why:** ADR-008 defines the policy: cloud only when the local model cannot meet the quality or capability bar, not on connection failure. Phase 4 added `ModelConfig.backend = "generic"` and `GenericChatClient`. The fallback logic itself — detecting "local cannot meet bar" and routing to a cloud model — is missing.

**What was built:**
- `infrastructure/chat/fallback.py`: `FallbackPolicy(mode)` — evaluates `LLMResponse` against `"no_tool_calls"` / `"malformed_args"` / `"always"` policies (unknown mode = never trigger). `FallbackChatClient(local, cloud, cloud_model, policy)` — calls local first; if policy triggers, calls cloud and queues a `cloud_fallback` event in `pop_events()`.
- `config/schema.py`: `CloudFallbackConfig(model_key, policy="no_tool_calls")` + `cloud_fallback: Optional[CloudFallbackConfig]` on `FabricConfig`. Defaults to `None` — identical behaviour when absent.
- `execute_task.py`: Auto-wraps injected `chat_client` with `FallbackChatClient` when `config.cloud_fallback` is set (local import + `build_chat_client` for cloud). Drains `pop_events()` after each LLM call and logs `cloud_fallback` runlog events with `reason`, `local_model`, `cloud_model`.
- `tests/test_chat_fallback.py`: 21 tests — policy unit tests (8), client unit tests (8), config tests (3), execute_task integration tests (2). All mocked; no real cloud call needed. Fast CI: 304 pass (+21).

**Files:** `infrastructure/chat/fallback.py` (new), `config/schema.py`, `application/execute_task.py`, `tests/test_chat_fallback.py` (new)

---

## Done

| Item | Completed | Summary |
|------|-----------|---------|
| P7-4: Docs update for Phase 7 | 2026-02-25 | STATE.md (phase 7 in progress → complete, CI 342); PLAN.md (Phase 7 deliverables all ticked); VISION.md §7 (Phase 7 in history) + §8 (enterprise integrations row updated); BACKLOG.md done table. |
| P7-3: Enterprise research specialist | 2026-02-25 | infrastructure/specialists/enterprise_research.py — cross_run_search tool (queries run index), file tools, web tools (network_allowed); SYSTEM_PROMPT_ENTERPRISE_RESEARCH (staleness/confidence notation, multi-source, structured reports); enterprise_research in DEFAULT_CONFIG with enterprise_search + github_search caps; registry._DEFAULT_BUILDERS updated; 16 tests — system prompt, capabilities, tool defs, cross_run_search execution, routing. Fast CI: 342 pass (+16). |
| P7-2: GitHub MCP integration | 2026-02-25 | tests/test_mcp_real_github.py — 4 tests (list_tools, search_repositories, get_file_contents, unknown_tool_returns_error); skip_if_github_token_missing + skip_if_npx_unavailable + skip_if_mcp_not_installed fixtures; github_search + enterprise_search capability IDs added to capabilities.py; docs/MCP_INTEGRATIONS.md with GitHub/Confluence/Jira/filesystem config examples. Fast CI: 326 pass (unchanged — real_mcp deselected). |
| P7-1: Semantic run index search | 2026-02-25 | RunIndexEntry.embedding (Optional[List[float]]); embed_text() via Ollama /api/embeddings (strips /v1 suffix); cosine_similarity(); semantic_search_index() with fallback to keyword; RunIndexConfig(embedding_model, embedding_base_url) on FabricConfig; execute_task embeds entry when configured; fabric logs search uses semantic when available. 22 tests. Fast CI: 326 pass (+22). |
| P6-4: Cloud LLM fallback | 2026-02-25 | FallbackPolicy (no_tool_calls / malformed_args / always) + FallbackChatClient with pop_events(); CloudFallbackConfig on FabricConfig; execute_task auto-wraps + logs cloud_fallback runlog events. 21 tests, all mocked. Fast CI: 304 pass (+21). |
| P6-3: Containerised workspace isolation (Podman) | 2026-02-25 | ContainerisedSpecialistPack — podman run/exec/stop lifecycle; :Z SELinux volume label; shell intercepted, other tools delegated; container_image on SpecialistConfig; registry wraps after MCP; 26 tests (22 unit + 4 real Podman). Fast CI: 283 pass (+26). |
| P6-2: Real MCP server smoke test | 2026-02-25 | tests/test_mcp_real_server.py — 5 tests using @modelcontextprotocol/server-filesystem via npx; fixtures skip gracefully when npx or mcp package absent; all 5 pass end-to-end. pyproject.toml: real_llm + real_mcp markers declared. Fast CI: 257 pass (unchanged). |
| P5-1 through P5-6: Phase 5 MCP tool server support | 2026-02-24 | MCPServerConfig + mcp_servers on SpecialistConfig; execute_tool async + aopen/aclose lifecycle; MCPSessionManager + converter; MCPAugmentedPack wrapper; registry transparent wrap; [mcp] optional dep. Fast CI: 243 pass (+34) |
| P4-1 through P4-4: Phase 4 observability + multi-backend LLM | 2026-02-24 | GenericChatClient + build_chat_client() factory + ModelConfig.backend; fabric logs list/show CLI; OpenTelemetry no-op shim + optional real OTEL (console/otlp); TelemetryConfig schema; execute_task spans (execute_task, llm_call, tool_call); setup_telemetry() wired into CLI + HTTP API lifespan; [otel] pyproject.toml extra. Fast CI: 194 pass (+50) |
| P3-1 through P3-5: Phase 3 multi-pack task force | 2026-02-24 | RecruitmentResult.specialist_ids (greedy selection); _execute_pack_loop(); sequential multi-pack execution with context handoff; pack_start events + prefixed step names; RunResult.specialist_ids + is_task_force; HTTP _meta updated; 17 new tests in test_task_force.py + 2 in test_capabilities.py. Fast CI: 144 pass (+22) |
| P2-1 through P2-5: Phase 2 capability routing | 2026-02-24 | CAPABILITY_KEYWORDS + capabilities on SpecialistConfig; infer_capabilities(); RecruitmentResult; two-stage routing (caps → keyword fallback); recruitment runlog event; required_capabilities in RunResult + HTTP _meta; docs/CAPABILITIES.md; REQUIREMENTS FR2 + VISION §8 updated. Fast CI: 122 pass (+17) |
| T3-5: Extract build_task() to domain | 2026-02-24 | build_task() in domain/models.py; (pack or "").strip() or None fixes subtle whitespace-only inconsistency between CLI and HTTP paths; exported from domain/__init__; 6 new tests |
| T3-4: Config validation at load time | 2026-02-24 | @model_validator on FabricConfig rejects empty specialists dict; docstring marks extension point for future cross-reference checks; 3 new tests |
| T3-3: Tie-breaking in recruit_specialist | 2026-02-24 | Explicit min(-score, config_index) replaces implicit max; docstring documents contract; 2 parametrized tie-break tests |
| T3-2: Parametrize tests | 2026-02-24 | test_packs, test_router, test_sandbox, test_llm_discovery; 94 pass (was 82; +12 named cases) |
| T3-1: Architecture diagram | 2026-02-24 | Complete rewrite of `docs/ARCHITECTURE.md`: ASCII layer overview, component map with all source files, data flow + sequence diagram, runlog events table, extension points, config/startup flow, dependency rule table |
| T2-5: Centralise magic numbers | 2026-02-24 | `config/constants.py` with 6 named constants + rationale comments; updated sandbox.py, execute_task.py, client.py, llm_discovery.py, engineering.py |
| T2-4: Log sandbox violations as security events | 2026-02-24 | `security_event` runlog entry alongside `tool_error` when `PermissionError` caught; 3 new tests |
| T2-3: Expand error-path test coverage | 2026-02-24 | 4 new tests: malformed args, multiple tool calls, finish_task + regular tool coexisting, unknown tool name |
| T2-2: Cache `load_config()` | 2026-02-24 | `@lru_cache(maxsize=1)`; autouse fixture in conftest.py resets cache between tests; 2 new tests |
| T2-1: Extract shared tool-definition helpers | 2026-02-24 | `tool_defs.py` with `make_tool_def()`, `make_finish_tool_def()`, shared file tool constants; engineering.py and research.py updated |
| T1-4: Extensible specialist registry | 2026-02-24 | `SpecialistConfig.builder` optional field; `_load_builder()` via importlib; `_DEFAULT_BUILDERS` dict; 12 new tests |
| T1-3: Structured logging | 2026-02-24 | `logging.NullHandler` at library root; per-module loggers; DEBUG/INFO/WARNING coverage; `--verbose` CLI flag |
| T1-2: Scoped exception handling in tool execution | 2026-02-24 | Four specific except clauses; `tool_error` runlog event (distinct from `tool_result`); 7 new tests; KeyboardInterrupt/SystemExit propagate normally |
| T1-1: Validate `finish_task` payload | 2026-02-24 | Required fields (pack-specific) validated before accepting; error returned to LLM as tool result so it can retry; 9 new tests in `tests/test_execute_task.py` |
| Phase 1: all 13 deliverables | 2026-02-23 | MVP with engineering + research packs, CLI, HTTP API, sandbox, runlog, local LLM |
| Native tool calling refactor | 2026-02-24 | Replaced JSON-in-content protocol with OpenAI function calling; `LLMResponse`/`ToolCallRequest` domain types; `finish_task` terminal tool |
| Fix `_param_size_sort_key` float parsing | 2026-02-24 | "8.0B" was parsed as 80 not 8; `sqlcoder:15b` was selected over `llama3.1:8b` as fallback; fixed with regex float parse |
| Fix "does not support tools" 400 handling | 2026-02-24 | `OllamaChatClient` now detects this specific error before retrying; raises clear `RuntimeError` |
| Fix `asyncio.to_thread` for `resolve_llm` in HTTP handler | 2026-02-24 | `resolve_llm` is blocking; was called directly in async FastAPI handler |
| Un-skip and fix `test_resolve_llm_filters_embedding_models` | 2026-02-24 | Wrong patch target fixed; test now passes |
| 5 new tests (packs, prompt content) | 2026-02-24 | `finish_task` in definitions, OpenAI format validation, prompt content checks |
| All 4 real-LLM E2E tests passing | 2026-02-24 | engineering, research, API POST, verify_working_real.py — all pass against Ollama 0.12.11 with llama3.1:8b |
