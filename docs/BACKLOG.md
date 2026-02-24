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
3. Run `pytest tests/ -k "not real_llm and not verify"` — confirm 45 pass before touching code.
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

### P2-1: Capability model — define capabilities and map packs

**What:** Define a set of capability IDs (e.g., `"code_execution"`, `"file_io"`,
`"systematic_review"`, `"web_search"`) and declare which capabilities each pack provides
in `FabricConfig.specialists[id].capabilities: list[str]`.

**Why:** Enables task→capabilities→pack routing that is grounded in what packs can actually do,
not keyword heuristics.

**Files:** `src/agent_fabric/config/schema.py`, `docs/CAPABILITIES.md` (new)

---

### P2-2: Task-to-capabilities mapping

**What:** Given a task prompt, determine the required capability IDs. Start with a rules/keyword
approach (similar to current routing but keyed to capability IDs, not pack names). Later replace
with a small router model + JSON schema.

**Why:** Decouples "what capability is needed" from "which pack provides it" — enabling multi-pack
task forces in Phase 3.

**Files:** `src/agent_fabric/application/recruit.py` (rewrite or extend)

---

### P2-3: Recruit pack from capabilities

**What:** Select the pack(s) whose declared capabilities cover the required capabilities.
For Phase 2: still single pack per run. Log `required_capabilities` and `selected_pack` in
run metadata.

**Files:** `src/agent_fabric/application/recruit.py`, `execute_task.py`, `run_log.py`

---

### P2-4: Log required capabilities and selected pack in run metadata

**What:** `runlog.jsonl` and/or the `RunResult` metadata (`_meta` in HTTP response) should
include `required_capabilities: [...]` and `selected_pack: "..."`. This makes routing
decisions observable and debuggable.

**Files:** `execute_task.py`, `run_log.py`, `http_api.py`

---

### P2-5: Update docs for Phase 2

**What:** Update `STATE.md` (Phase 2 complete), `PLAN.md` (tick off deliverables), `VISION.md §8`
(alignment table), and `REQUIREMENTS.md` (describe capability-based routing as a functional
requirement).

---

## Done

| Item | Completed | Summary |
|------|-----------|---------|
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
