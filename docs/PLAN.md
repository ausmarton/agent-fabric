# agent-fabric: Iterative Build Plan

This document defines **phases**, **deliverables**, and **verification gates** so the system can be built incrementally and any session (human or agent) can **resume** with full context.

---

## Resumability: how to pick up work across restarts

**When you (or another agent) start or resume work on this repo:**

1. **Read [STATE.md](STATE.md)** — current phase, what’s done, what’s next, last updated.
2. **Read this PLAN** — at least the section for the phase in STATE (e.g. Phase 1).
3. **Run the verification for that phase** (see “Verification” below and per-phase gates). If something fails, fix it before adding new work.
4. **Proceed** with the next unchecked deliverable for the current phase, or move to the next phase if the current one is complete.

**Key docs:**

| Doc | Purpose |
|-----|--------|
| [STATE.md](STATE.md) | Single source of truth: current phase, completed items, next steps. **Update STATE when you complete or start work.** |
| [PLAN.md](PLAN.md) (this file) | Phases, deliverables, verification criteria. |
| [VISION.md](VISION.md) | Long-term vision, principles, use cases (illustrative). |
| [../REQUIREMENTS.md](../REQUIREMENTS.md) | Functional requirements and validation for the MVP. |
| [../README.md](../README.md) | User-facing quickstart and usage. |

---

## Verification strategy (checks we run)

- **Automated (every change / before merge):**
  - `pytest tests/ -v` — all tests pass.
  - Lint (if configured): e.g. `ruff check src/agent_fabric`.
- **Manual (per phase or before marking phase complete):**
  - CLI: `fabric --help`, `fabric run --help`; `fabric run "…" --pack engineering` (with or without LLM server) behaves as in REQUIREMENTS.
  - API: `fabric serve` + `curl http://127.0.0.1:8787/health`.
  - Run structure: `.fabric/runs/<id>/runlog.jsonl` and `workspace/` exist after a run.
- **E2E (when LLM server available):**
  - One engineering run and one research run as in REQUIREMENTS “End-to-end validation”; inspect artifacts and runlog.

**Rule:** Do not mark a phase complete until its verification gate passes. Update STATE.md when you run verification or complete deliverables.

---

## Phase 1: Solid MVP (current baseline)

**Goal:** A working fabric with one-pack-per-run recruitment, engineering and research packs, local LLM only, and enough tests and docs to iterate safely.

**What Phase 1 delivers (outcomes):**
- You can run `fabric run "your prompt"` (or `--pack engineering` / `--pack research`) and get a run directory with a structured runlog and workspace; the router picks a pack when you don’t specify one.
- You can run `fabric serve` and hit `GET /health` and `POST /run` to drive the same behaviour over HTTP.
- Config is default + optional file via `FABRIC_CONFIG_PATH`; model params (temperature, max_tokens) are passed to the LLM.
- Engineering and research packs each have tools and workflows; quality gates (no “works” without tests, deploy proposed only, citations only from fetch) are in the prompts.
- Sandbox keeps file and shell operations scoped and safe; automated tests plus a clear verification gate prove the above.

### Deliverables (Phase 1)

| # | Deliverable | Where it lives | Verification |
|---|-------------|----------------|--------------|
| 1.1 | CLI: `fabric run`, `fabric serve`, options | `src/agent_fabric/interfaces/cli.py` | `fabric --help`, `fabric run --help` |
| 1.2 | HTTP API: `/health`, `POST /run` | `src/agent_fabric/interfaces/http_api.py` | `curl .../health`, POST with prompt |
| 1.3 | Config: defaults + optional file via `FABRIC_CONFIG_PATH` | `src/agent_fabric/config/` | Config load test; env override |
| 1.4 | Recruit: keyword scoring + fallback (engineering vs research) | `src/agent_fabric/application/recruit.py` | `tests/test_router.py` |
| 1.5 | Execute task: run dir, workspace, runlog, one pack per run | `src/agent_fabric/application/execute_task.py` | Run once; check run dir structure |
| 1.6 | Engineering specialist: tools + prompts | `src/agent_fabric/infrastructure/specialists/engineering.py` | Run with `--pack engineering`; runlog has tool_call |
| 1.7 | Research specialist: tools + prompts | `src/agent_fabric/infrastructure/specialists/research.py` | Run with `--pack research`; `network_allowed` gates web tools |
| 1.8 | Sandbox: path safety, shell allowlist | `src/agent_fabric/infrastructure/tools/sandbox.py` | `tests/test_sandbox.py` |
| 1.9 | Runlog and model params passed to LLM | `src/agent_fabric/infrastructure/workspace/run_log.py`; execute_task uses `model_cfg` | Runlog exists; temperature/max_tokens in use |
| 1.10 | Quality gates in prompts (no “works” without tests; deploy proposed only; citations only from fetch) | Workflow system rules, REQUIREMENTS FR5 | README + REQUIREMENTS |
| 1.11 | Automated tests for router, sandbox, json_tools, prompts, config, packs | `tests/` | `pytest tests/ -v` |
| 1.12 | Docs: README, REQUIREMENTS, VISION, PLAN, STATE | Various | All referenced docs exist and linked |
| 1.13 | Local LLM default and core (ensure available by default) | Config + ensure_llm_available in CLI/API; opt-out | local_llm_ensure_available: true by default; test_config, test_llm_bootstrap, test_backends_alignment |

### Phase 1 verification gate

- [ ] **Full validation:** `python scripts/validate_full.py` passes (ensures real LLM, then all 42 tests run including at least a couple of real-LLM E2E tests; those E2E runs are essential for integration assurance).
- [ ] `fabric run "list files" --pack engineering` creates `.fabric/runs/<id>/runlog.jsonl` and `workspace/` (fails at LLM if no server; that’s OK).
- [ ] `fabric serve` and `curl http://127.0.0.1:8787/health` return `{"ok": true}`.
- [ ] REQUIREMENTS.md “Manual validation” items 1–4 pass.

**Phase 1 acceptance (we're done when):** All 13 deliverables implemented; full validation (scripts/validate_full.py) run and passed so at least a couple of real-LLM E2E tests have run and passed (integration assurance); manual checks: CLI help, `fabric run` creates run dir + runlog + workspace, `fabric serve` + `/health` returns `{"ok": true}`. Update STATE.md to “Phase 1 complete” and set “Next: Phase 2”.

---

## Phase 2: Task decomposition and smarter routing

**Goal:** Move from “keyword router picks one pack” to “task is analysed → required capabilities → which pack(s) to recruit”. Still one pack per run as a first step, but the *decision* is capability-based and documented so we can later add multi-pack.

**What Phase 2 delivers (outcomes):** A capability model and config mapping packs to capabilities; for each run, required capabilities and selected pack(s) recorded in runlog or metadata; routing selects pack by capabilities (still one pack per run); tests and docs updated.

### Deliverables (Phase 2)

| # | Deliverable | Verification |
|---|-------------|--------------|
| 2.1 | **Capability model** — define capabilities (e.g. “data_engineering”, “systematic_review”, “web_search”) and map packs to capabilities in config. | Config schema + docs; router or new module uses it. |
| 2.2 | **Task → capabilities** — either (a) keyword/schema rules or (b) small router model + JSON schema that, given a task, outputs required capability IDs. | Unit tests; deterministic or model-based path. |
| 2.3 | **Recruitment** — select pack(s) that cover required capabilities (for Phase 2: still single pack; multi-pack in Phase 3). | Router returns one pack; log “required capabilities” and “selected pack”. |
| 2.4 | **Runlog / observability** — log “task”, “required_capabilities”, “selected_pack(s)” in run metadata or runlog. | Inspect runlog or result `_meta`. |
| 2.5 | **Docs** — update VISION §8 alignment and REQUIREMENTS to describe capability-based routing. | STATE and PLAN updated. |

**Phase 2 acceptance (we’re done when):**
- Capability model and task→capabilities (rules or model) implemented; recruitment selects pack from capabilities.
- Run metadata or runlog includes required_capabilities and selected_pack; tests and manual run confirm.
- Phase 1 verification gate still passes.

### Phase 2 verification gate

- [ ] `pytest tests/ -v` passes (including any new tests for capabilities/routing).
- [ ] For a few prompts, run and confirm selected pack and (if implemented) required capabilities are logged.
- [ ] Phase 1 verification gate still passes.

---

## Phase 3: Multi-pack task force — **complete**

**Goal:** For a single task, recruit and run **multiple** packs (e.g. engineering + research) that together form a task force. Orchestration may be sequential or coordinated.

### Deliverables (Phase 3)

| # | Deliverable | Status | Verification |
|---|-------------|--------|--------------|
| 3.1 | Task decomposition outputs *multiple* capability IDs when needed. | Done | `infer_capabilities()` returns all matching caps; `_greedy_select_specialists()` covers multi-pack selection. `tests/test_task_force.py`. |
| 3.2 | Supervisor runs multiple packs; shared workspace + combined runlog. | Done | `execute_task()` loops over `specialist_ids`; one run dir; `pack_start` events; `specialist_ids` on `RunResult`. |
| 3.3 | Coordination: sequential handoff with context forwarding. | Done | Each pack receives previous pack's `finish_task` payload as context; step names prefixed by specialist ID. |
| 3.4 | Docs and STATE updated. | Done | BACKLOG.md Phase 3 section; STATE.md; this PLAN updated. |

**Phase 3 acceptance:** All 4 deliverables implemented; fast CI: **144 pass** (+22). `RecruitmentResult.is_task_force` and `RunResult.is_task_force` both work correctly for mixed-capability prompts.

---

## Phase 4: Observability and multi-backend LLM — **complete**

**Goal:** Add production-grade observability (OpenTelemetry spans), a `fabric logs` CLI for inspecting past runs, and a generic LLM client so cloud/enterprise LLM endpoints work without Ollama quirks. All optional/additive: no breaking changes to existing functionality.

### Deliverables (Phase 4)

| # | Deliverable | Status | Notes |
|---|-------------|--------|-------|
| 4.1 | Generic/cloud LLM client + `ModelConfig.backend` | Done | `infrastructure/chat/__init__.py` (`build_chat_client()` factory); `GenericChatClient` (no Ollama 400 retry); shared `parse_chat_response()` in `_parser.py`; `backend: str = "ollama"` on `ModelConfig`; CLI + HTTP API updated; 15 new tests |
| 4.2 | `fabric logs` CLI subcommand | Done | `logs list` (Rich table, sorted most-recent-first) + `logs show` (pretty JSON with `--kinds` filter); `RunSummary` dataclass + `list_runs()` + `read_run_events()` in `infrastructure/workspace/run_reader.py`; 18 new tests |
| 4.3 | OpenTelemetry tracing (optional dep) | Done | `infrastructure/telemetry.py` (`_NoOpSpan`, `_NoOpTracer`, `setup_telemetry()`, `get_tracer()`); graceful no-op when OTEL not installed; `TelemetryConfig` in config schema; `fabric.execute_task` / `fabric.llm_call` / `fabric.tool_call` spans; `[otel]` extra in `pyproject.toml`; wired into CLI + HTTP API lifespan; 13 new tests |
| 4.4 | Docs update | Done | BACKLOG.md Phase 4 section; STATE.md phase + CI count; PLAN.md Phase 4 concrete deliverables |

**Phase 4 acceptance:** All 4 deliverables implemented; fast CI: **194 pass** (+50 vs Phase 3). `ModelConfig.backend = "generic"` routes to `GenericChatClient`; `fabric logs list` shows past runs; OTEL spans emitted when `telemetry.enabled=true`.

---

## Phase 5: MCP tool server support — **complete**

**Goal:** Enable specialist packs to delegate tool calls to external MCP (Model Context Protocol) servers without writing custom Python adapters. Zero changes required to pack factories — just add `mcp_servers:` entries to the YAML/JSON config. The MCP session lifecycle (connect, call, disconnect) is managed by the framework around the tool loop.

### Deliverables (Phase 5)

| # | Deliverable | Status | Notes |
|---|-------------|--------|-------|
| 5.1 | Config schema: `MCPServerConfig` + `mcp_servers` on `SpecialistConfig` | Done | `config/schema.py`; stdio and SSE transports; validators; duplicate-name check; +6 tests in `test_config.py` |
| 5.2 | Async `execute_tool` + `aopen`/`aclose` lifecycle | Done | `base.py`, `ports.py`, `execute_task.py` (_execute_pack_loop wrapped in try/finally); `_StubPack` in registry tests updated |
| 5.3 | `MCPSessionManager` + `mcp_tool_to_openai_def` converter | Done | `infrastructure/mcp/session.py`, `converter.py`; guarded mcp imports; +12 mocked tests |
| 5.4 | `MCPAugmentedPack` wrapper | Done | `infrastructure/mcp/augmented_pack.py`; asyncio.gather for connect/disconnect; +10 tests |
| 5.5 | Registry wraps pack transparently | Done | `registry.py`; RuntimeError when mcp not installed; +6 tests in `test_mcp_registry.py` |
| 5.6 | `pyproject.toml` + docs | Done | `mcp = ["mcp>=1.0"]` optional dep; `dev` dep includes mcp; all docs updated |

**Phase 5 acceptance:** All 6 deliverables implemented; fast CI: **~242 pass** (+33 vs Phase 4). `SpecialistConfig(mcp_servers=[MCPServerConfig(...)])` in config causes `get_pack()` to return `MCPAugmentedPack`; tool loop calls `aopen()`/`aclose()`; MCP tools are prefixed `mcp__<name>__<tool>`.

---

## Phase 6+: Containerisation and enterprise scale (backlog)

- **Containerised workers (e.g. Podman)** per specialist role, spun up on demand.
- **Persistent vector store** for enterprise RAG (metadata, staleness).
- **Cloud fallback** when local model cannot meet the bar.

Update PLAN with concrete deliverables when Phase 6 begins.

---

## Summary

- **Resume by:** Reading STATE.md → PLAN.md (current phase) → run verification → do next deliverable.
- **Always:** Keep STATE.md updated when completing or starting work; run `pytest tests/ -v` before considering a phase done.
- **Value:** Phase 1 delivers a working, testable, documented fabric; Phase 2 aligns routing with the vision (task → capabilities → recruit); Phase 3 enables multi-pack task forces; Phase 4 adds observability and multi-backend LLM; Phase 5 adds MCP tool server support.
