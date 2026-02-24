# agent-fabric: Architecture Decision Records

**Purpose:** Records of significant technical decisions — *what* was decided, *why*, and
*what it means for future work*. Prevents re-litigating settled questions. When a decision
is revisited or superseded, mark the old record as Superseded and add a new one.

**Format:** Each record has Status, Context, Decision, and Consequences.

---

## ADR-001: Hexagonal architecture (ports and adapters)

**Status:** Accepted
**Date:** 2026-02-23

**Context:** The system needs to work with multiple LLM backends (Ollama, vLLM, OpenAI), multiple
interfaces (CLI, HTTP API), and multiple specialist packs. We also need to unit-test the application
logic without a real LLM or filesystem.

**Decision:** Use a strict layered hexagonal architecture:
- `domain/` — pure data structures and errors; no I/O, no external dependencies.
- `application/` — orchestration logic; depends on `domain/` and defines ports (protocols) that
  infrastructure must implement. Never imports from `infrastructure/` or `interfaces/`.
- `infrastructure/` — concrete adapters (LLM client, filesystem, specialists, tools).
- `interfaces/` — CLI (Typer) and HTTP (FastAPI) entry points; inject concrete infrastructure into application.
- `config/` — schema (Pydantic) and loading; can be imported by any layer.

**Consequences:**
- Adding a new LLM backend = implement `ChatClient` protocol (~30 lines). No other changes needed.
- Adding a new specialist = implement `SpecialistPack` and register it (see ADR-006).
- `application/execute_task.py` is fully testable with mocks — no real LLM or filesystem needed.
- All interfaces (CLI, HTTP) inject the same application function; behaviour is identical.

---

## ADR-002: Native OpenAI function calling (tools API) over JSON-in-content

**Status:** Accepted (supersedes original JSON-in-content design)
**Date:** 2026-02-24

**Context:** The original implementation required the LLM to output a specific JSON schema in
its message content (`{"action": "tool", "tool_name": "...", "args": {...}}`). This was fragile:
LLMs would add prose, wrap the JSON in markdown, or produce invalid JSON. Parsing required a
custom extraction pass. Every LLM call could fail in a new way.

**Decision:** Use the standard OpenAI `tools` parameter and `tool_calls` response field. The LLM
receives tool definitions as structured API input (not as prompt text); it emits tool calls as
structured API output (not as freeform text). The `finish_task` tool is the terminal signal
(see ADR-003).

**Consequences:**
- System prompts are clean — no JSON schema embedded in prompts.
- Tool calls are reliably parsed from structured API fields.
- Requires a tool-capable model (see ADR-007).
- `ChatClient.chat()` now accepts `tools: list[dict] | None` and returns `LLMResponse`
  (with `content` + `tool_calls` fields) instead of `str`.
- The 400 error handling in `OllamaChatClient` detects "does not support tools" and raises a
  clear `RuntimeError` before attempting a retry.

---

## ADR-003: `finish_task` as the terminal tool signal

**Status:** Accepted
**Date:** 2026-02-24

**Context:** The tool loop needs a stopping condition. Options considered:
1. LLM returns a message with no tool calls → treat as done.
2. LLM calls a special `finish_task` tool → treat as done.
3. A separate `stop` field in the response.

**Decision:** Option 2: a `finish_task` tool is included in every specialist pack's tool
definitions. When the LLM calls it, the loop terminates and the tool arguments become the
`RunResult.payload`. Option 1 is also handled as a fallback (plain text response with no tool
calls produces a minimal final payload) but is not the expected path.

**Consequences:**
- `finish_task` arguments are the final output format. Each pack defines its own schema
  (engineering: summary/artifacts/next_steps/notes; research: richer with citations, etc.).
- `finish_task` is NOT in `BaseSpecialistPack._tools` (the executor map) — it is handled
  specially in `execute_task.py`. Attempting to call `pack.execute_tool("finish_task", ...)`
  will raise `KeyError`. This is intentional.
- Required fields are validated before accepting the payload (BACKLOG T1-1 — done 2026-02-24).
  If any required field is missing, the error is returned to the LLM as a tool result so it can retry.

---

## ADR-004: `resolve_llm` for model discovery (don't hard-require a specific model)

**Status:** Accepted
**Date:** 2026-02-24

**Context:** The default config references `qwen2.5:7b` and `qwen2.5:14b`, but these models
may not be pulled on the user's machine. Failing with "model not found" on first run is a bad
experience. We also want the system to work out-of-the-box with whatever model the user has.

**Decision:** `resolve_llm(config, model_key)` queries the backend for available models and
selects the best match: the configured model if it exists, otherwise the smallest available
chat-capable model by parameter size. This means "best available" rather than "exact match".

**Consequences:**
- First run works without pulling a specific model.
- The `_param_size_sort_key` function must parse `"8.0B"` correctly as 8.0 (not 80 — a bug
  fixed 2026-02-24 with regex float parse).
- Embedding-only models are excluded from selection (filter in `_is_ollama_chat_capable`).
- Models that don't support tool calling (e.g. `sqlcoder:15b`) will cause a clear error if
  selected; the fix is to have a tool-capable model available (see ADR-007).
- `resolve_llm` is a synchronous blocking call (HTTP). In async contexts (FastAPI handler)
  it must be called via `asyncio.to_thread`.

---

## ADR-005: Sandbox scoping for file and shell tools

**Status:** Accepted
**Date:** 2026-02-23

**Context:** The engineering pack gives the LLM access to shell execution and file I/O. Without
scoping, the LLM could read or write arbitrary files on the host, or run arbitrary commands.

**Decision:**
- File tools (`read_file`, `write_file`, `list_files`) use `safe_path()` which resolves the
  real path and checks it is within the workspace root. `PermissionError` is raised otherwise.
- Shell tool (`shell`) uses a command allowlist (`SandboxPolicy.allowed_commands`). Commands not
  on the list raise `PermissionError`. The subprocess runs with `cwd=workspace_root`.
- `network_allowed` in the research pack gates web tools (web_search, fetch_url) — not
  implemented at the OS/network layer, just at the tool level.

**Consequences:**
- The shell allowlist must be maintained as new tools/languages are needed.
- Network is not OS-blocked even when `network_allowed=False` — the engineering pack's shell
  can still reach the network. This is intentional (documented) and acceptable for the current
  phase; true network sandboxing would require containers (Phase 4).
- Sandbox violations (PermissionError) produce a `tool_error` runlog event *and* a distinct
  `security_event` entry with `event_type: "sandbox_violation"` (BACKLOG T2-4 — done 2026-02-24).

---

## ADR-006: Extensible specialist registry (config-driven builders + MCP transparent wrap)

**Status:** Accepted — fully implemented
**Date:** 2026-02-24 (T1-4 completed); 2026-02-24 (Phase 5 MCP wrap added)

**Context:** Specialist packs need to be discoverable and constructable from a `specialist_id`
string. The original implementation used a hardcoded `_BUILDERS` dict in `registry.py`.

**Decision (T1-4 — done):** `SpecialistConfig` carries an optional `builder` field (dotted
import path, e.g. `"mypackage.packs.custom:build_custom_pack"`). `ConfigSpecialistRegistry`
imports and calls it at `get_pack()` time. A fallback `_DEFAULT_BUILDERS` map covers the
built-in `engineering` and `research` packs. Adding a new pack requires only a config entry —
no changes to `registry.py`.

**Decision (Phase 5 — done):** When `SpecialistConfig.mcp_servers` is non-empty, `get_pack()`
transparently wraps the returned pack in `MCPAugmentedPack`. The inner pack factory is
unaware of MCP; MCP attachment is a registry concern. Import of the `mcp` infrastructure is
lazy and guarded: a clear `RuntimeError` is raised if the optional `mcp` package is absent.

**Consequences:**
- Adding a new specialist pack = add a `builder:` entry to config. No registry edits needed.
- MCP tool servers are attached per-specialist in config. Pack factories need no changes.
- The `SpecialistPack` protocol is stable; the registry is the only place that handles wrapping.
- `execute_tool` is `async def` (ADR-011); sync tool functions are called directly without an executor.

---

## ADR-007: Require a tool-capable model; no fallback to JSON-in-content

**Status:** Accepted
**Date:** 2026-02-24

**Context:** When a model doesn't support tool calling (e.g. `sqlcoder:15b`), Ollama returns
`400 {"error": "... does not support tools"}`. We considered falling back to the original
JSON-in-content protocol.

**Decision:** No fallback. If the model doesn't support tools, raise a clear `RuntimeError`
with instructions to use a tool-capable model. Do not silently degrade to JSON-in-content.

**Rationale:** JSON-in-content is unreliable. Maintaining two code paths adds complexity.
The ecosystem of tool-capable local models is large enough (llama3.1, mistral, qwen2.5-coder,
deepseek-coder, etc.) that requiring one is reasonable. A clear error with guidance is better
than silently degraded behaviour.

**Consequences:**
- Users must have at least one tool-capable model pulled. The README should document this.
- `resolve_llm` currently selects by size without checking tool capability. If the smallest
  model happens to be tool-incapable, the user gets a clear error at runtime. A future
  improvement would probe tool capability during discovery (adds latency; deferred).

---

## ADR-008: Local-first LLM; cloud only when local capability/quality is insufficient

**Status:** Accepted
**Date:** 2026-02-23

**Context:** The vision is explicit: local LLM is the default and primary path. Cloud is used
only when local cannot meet quality or capability (not when the server is unreachable).

**Decision:** All current code targets local Ollama. `local_llm_ensure_available: true` by
default means the fabric starts Ollama if it isn't running. No cloud path exists yet.

**Consequences:**
- Cloud fallback is future (Phase 4+). When implemented, it must be triggered by "local model
  cannot meet quality or capability bar" — not by connection failures.
- The distinction matters architecturally: "server unreachable → start it" vs
  "model capability insufficient → use cloud model" are different code paths.

---

## ADR-009: Runlog as primary observability artifact

**Status:** Accepted
**Date:** 2026-02-23

**Context:** We need to be able to replay, debug, and audit every task run. Options:
1. Structured log per run (`runlog.jsonl`).
2. Global application log.
3. OpenTelemetry traces.

**Decision:** Per-run `runlog.jsonl` as the primary artifact. Every LLM request/response and
tool call/result is appended. Global application logging (option 2) is a pending addition
(BACKLOG T1-3) for operational concerns (HTTP request handling, startup, errors). OpenTelemetry
(option 3) is Phase 4+.

**Consequences:**
- Debugging a specific task = open its `runlog.jsonl`.
- Operational monitoring (what's the server doing right now?) is not possible until T1-3 is done.
- `runlog.jsonl` format is append-only JSONL; each line is `{"kind": "...", "ts": "...", ...}`.
  This format is stable and any change must be backward-compatible.

---

## ADR-010: Async-first application layer; sync tool implementations are acceptable

**Status:** Accepted (amended by Phase 5 — see ADR-011)
**Date:** 2026-02-24

**Context:** The tool loop is async (LLM calls are awaited). Individual tools (shell, file I/O,
web fetch) are sync functions. We could make tools async to allow concurrent execution.

**Decision:** The `SpecialistPack.execute_tool()` method is `async def` (as of Phase 5;
see ADR-011), but the underlying tool implementations remain sync functions called directly
from within `execute_tool`. Sequential execution (one tool per LLM turn) is preserved.
This is acceptable because:
1. Current pack tools are fast relative to LLM round-trips.
2. Sequential tool execution is predictable and easier to reason about.
3. The LLM drives the loop; it does not issue parallel tool calls within a single turn.

**Consequences:**
- Blocking sync calls in tools (subprocess, file I/O, httpx.Client) block the event loop for
  their duration. For short-running tools this is fine.
- `fetch_url` (research pack) uses `httpx.Client` (sync). If tool execution ever becomes
  concurrent, this will need refactoring to `httpx.AsyncClient`.
- `resolve_llm` (blocking) is correctly offloaded via `asyncio.to_thread` in the HTTP handler
  because it runs at request startup, outside the tool loop.
- MCP tool calls (`session.call_tool()`) are natively async and benefit from the async signature.

---

## ADR-011: Async pack lifecycle (`aopen`/`aclose`) for MCP subprocess management

**Status:** Accepted
**Date:** 2026-02-24

**Context:** MCP tool servers run as subprocesses (stdio transport) or long-lived HTTP
connections (SSE transport). They must be started before the tool loop begins and shut down
after it ends — even if the loop raises an exception. A sync interface cannot cleanly express
this because the connection/disconnection calls are themselves async (MCP SDK uses anyio).

**Decision:**
- `SpecialistPack.execute_tool()` is promoted to `async def` (Phase 5).
- `aopen()` and `aclose()` async lifecycle hooks are added to the `SpecialistPack` Protocol
  and `BaseSpecialistPack` (no-op defaults, so existing packs need no changes).
- `MCPAugmentedPack` overrides both: `aopen()` connects all sessions and populates MCP tool
  definitions; `aclose()` disconnects all sessions with `return_exceptions=True` so one
  failing disconnect never prevents the others from running.
- In `_execute_pack_loop`, `aopen()` is called *inside* a `try/finally` block so that `aclose()`
  is guaranteed to run even if `aopen()` itself raises partway through. This prevents leaking
  partially-connected MCP sessions.
- Tool names are namespaced `mcp__<server_name>__<tool>` to avoid collisions with native tools.

**Alternatives considered:**
- Context-manager protocol (`__aenter__`/`__aexit__`): cleaner for direct `async with` use,
  but would require changes to `_execute_pack_loop` callsites and adds complexity for callers
  that don't want lifecycle management (e.g. tests). The explicit `aopen`/`aclose` pair is
  simpler and works identically from the loop's perspective.
- Making sync tools async via `asyncio.to_thread`: unnecessary overhead. Sync functions called
  from an `async def execute_tool` are fine as long as they complete quickly.

**Consequences:**
- All test stubs implementing `SpecialistPack` must change `execute_tool` to `async def`.
- MCP server subprocesses are always cleaned up via the `finally` block in `_execute_pack_loop`.
- The optional `mcp` package is never imported at module level in `session.py`; the import is
  guarded by `try/except ImportError` and a `_MCP_AVAILABLE` flag, so the `infrastructure/mcp`
  package is importable without the dep installed. The registry performs a lazy import and raises
  a clear `RuntimeError` with an install hint when `mcp_servers` is configured without the package.
