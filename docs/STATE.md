# agent-fabric: Current State

**Purpose:** Single source of truth for “where we are” so any human or agent can resume work across restarts and sessions.

**Last updated:** 2026-02-26. Fast CI: **402 pass** (T1 + T2 + T3 tiers complete; Phases 2–9 complete).

---

## Current phase: **Phase 9 complete**

Phases 6, 7, and 8 are all **complete**. Phase 8 items (P8-1 through P8-4) are all done.

- **P6-1:** Persistent cross-run run index (`run_index.jsonl`) + `fabric logs search`.
- **P6-2:** Real MCP server smoke test (`tests/test_mcp_real_server.py`, `@pytest.mark.real_mcp`).
- **P6-3:** Containerised workspace isolation — `ContainerisedSpecialistPack` runs `shell` inside Podman; `SpecialistConfig.container_image` triggers transparent wrapping.
- **P6-4:** Cloud LLM fallback — `FallbackChatClient` + `FallbackPolicy`; `CloudFallbackConfig` on `FabricConfig`; `cloud_fallback` runlog events; auto-wrapping in `execute_task`.
- **P7-1:** Semantic run index search — `embed_text()` via Ollama `/api/embeddings`; `cosine_similarity()`; `semantic_search_index()` with keyword fallback; `RunIndexConfig` on `FabricConfig`; `execute_task` embeds on success; `fabric logs search` uses semantic when available. 22 tests.
- **P7-2:** GitHub MCP real integration test + `docs/MCP_INTEGRATIONS.md`; `github_search` + `enterprise_search` capabilities added.
- **P7-3:** `enterprise_research` specialist — `cross_run_search` tool (queries run index), staleness/confidence system prompt, `enterprise_search` + `github_search` capabilities; in `DEFAULT_CONFIG`. 16 tests.
- **P7-4:** Docs update — STATE.md, PLAN.md, VISION.md §7+§8, BACKLOG.md all updated.
- **P8-1:** Parallel task force execution — `task_force_mode` on `FabricConfig`; `_run_task_force_parallel()` + `_merge_parallel_payloads()` in `execute_task.py`; 14 tests.
- **P8-2:** SSE run event streaming — `event_queue: Optional[asyncio.Queue]` on `execute_task()`; `_emit()` helper; `POST /run/stream` SSE endpoint; `run_complete` runlog event; 6 tests.
- **P8-3:** Run status endpoint — `GET /runs/{run_id}/status`; reads `run_complete` event for completion detection; 6 tests.
- **P8-4:** Docs update — STATE.md, BACKLOG.md, PLAN.md updated.

---

## Phase 1 checklist (from [PLAN.md](PLAN.md))

| # | Deliverable | Status | Notes |
|---|-------------|--------|--------|
| 1.1 | CLI: `fabric run`, `fabric serve` | Done | `src/agent_fabric/interfaces/cli.py` |
| 1.2 | HTTP API: `/health`, `POST /run` | Done | `src/agent_fabric/interfaces/http_api.py` |
| 1.3 | Config: defaults + `FABRIC_CONFIG_PATH` | Done | `agent_fabric.config.load_config` |
| 1.4 | Recruit: keyword + fallback | Done | `agent_fabric.application.recruit`; `tests/test_router.py` |
| 1.5 | Execute task: run dir, workspace, runlog, one pack | Done | `agent_fabric.application.execute_task` |
| 1.6 | Engineering specialist | Done | `src/agent_fabric/infrastructure/specialists/engineering.py` |
| 1.7 | Research specialist | Done | `src/agent_fabric/infrastructure/specialists/research.py`; web tools gated by `network_allowed` |
| 1.8 | Sandbox: path safety, shell allowlist | Done | `src/agent_fabric/infrastructure/tools/sandbox.py`; `tests/test_sandbox.py` |
| 1.9 | Runlog + model params to LLM | Done | `model_cfg` passed; runlog in run dir |
| 1.10 | Quality gates in prompts | Done | FR5; deploy proposed only; citations from fetch only |
| 1.11 | Automated tests | Done | `tests/` — router, sandbox, json_tools, prompts, config, packs |
| 1.12 | Docs: README, REQUIREMENTS, VISION, PLAN, STATE | Done | This file + PLAN + VISION + REQUIREMENTS |
| 1.13 | Local LLM default and core (ensure available by default) | Done | `local_llm_ensure_available: true` by default; [SELF_CONTAINED_LLM.md](SELF_CONTAINED_LLM.md); `ensure_llm_available` in CLI/API; opt-out for managed server |

---

## Phase 1 verification gate (run before marking Phase 1 complete)

**Integration assurance** requires **at least a couple of E2E tests that run against a real LLM** to run and pass. Mocked and unit tests add value (fast feedback, wiring, contracts); real-LLM E2E are essential to ensure everything is integrated and working as expected.

- [x] **Full validation (proves system works):** `python scripts/validate_full.py` — ensures LLM is reachable (starts it if configured), then runs pytest so **all 42 tests** run (no skips). Must pass. If no LLM can be reached or started, the script exits with failure and does not run tests.
- [x] **Run dir:** `fabric run "list files" --pack engineering` → creates `.fabric/runs/<id>/runlog.jsonl` and `workspace/` (connection error without LLM server is expected).
- [x] **API:** `fabric serve` then `curl http://127.0.0.1:8787/health` → `{"ok": true}`. `POST /run` without LLM returns **503** with a clear detail message.
- [x] **REQUIREMENTS:** Manual validation items 1–4 in REQUIREMENTS.md hold (CLI help, routing, run structure, API health).
- [x] **E2E (real LLM):** With a real LLM available, `python scripts/verify_working_real.py` → exits 0; runlog has tool_call and tool_result; workspace has artifacts. Same is asserted by the real-LLM pytest tests when run via `validate_full.py`.

**Fast CI:** `pytest tests/ -k "not real_llm and not verify"` → **194 pass** (4 real-LLM tests deselected). Use for quick feedback on wiring and unit/integration behaviour; it does not replace the need to run real-LLM E2E for integration assurance.

**Phase 1 complete.** Full validation (2026-02-24): fast CI 45 pass; all 4 real-LLM E2E tests pass against Ollama 0.12.11 with llama3.1:8b (resolve_llm auto-discovers the available model). `verify_working_real.py` exits 0. Next: Phase 2.

**Verification passes (multi-pass checklist):** See [VERIFICATION_PASSES.md](VERIFICATION_PASSES.md). Last run 2026-02-24: fast CI 45 pass; real-LLM tests (engineering, research, API, verify_script) all PASS with llama3.1:8b on Ollama 0.12.11.

---

## Phase 1: what’s tested, what’s not

**Fully tested / demonstrated**

All Phase 1 functional requirements (FR1–FR6 in REQUIREMENTS.md) have automated test coverage or are covered by the verification gate and E2E runs.

| Area | How it’s tested |
|------|------------------|
| CLI `fabric run` / `fabric serve` | pytest (integration + API); real CLI run with real LLM (engineering task). |
| API `GET /health`, `POST /run` | pytest (health, POST with mocked execute_task); POST without LLM → 503. |
| Config, recruit, sandbox, runlog, packs | Unit and integration tests (test_config, test_router, test_sandbox, test_packs, test_integration, etc.). |
| Engineering pack with real LLM, tool use, artifacts | `verify_working_real.py` (exits 0; tool_call/tool_result; workspace e.g. hello.txt). |
| Run dir structure (runlog.jsonl, workspace/) | All E2E and integration tests. |
| Routing (keyword + fallback), research pack tool list (network_allowed) | test_router, test_packs. |
| Local LLM default (config, ensure_available in code) | test_config, test_llm_bootstrap; real run uses Ollama when available. |
| BACKENDS/REQUIREMENTS alignment (backend-agnostic, ensure when enabled, run dir only under workspace_root) | `tests/test_backends_alignment.py`: ChatClient port only, config defaults, API ensure_llm_available when enabled / skipped when opted out, run dir under workspace_root. |

**Recommended for full demonstration (manual or when LLM available)**

| Check | Command / how |
|-------|----------------|
| **Research pack with real LLM** (REQUIREMENTS §6) | `fabric run "Mini systematic review of post-quantum crypto performance." --pack research` (with `network_allowed` true if you want web tools). Inspect runlog for web_search/fetch_url and workspace for deliverables. |
| **API POST /run with real LLM** | `fabric serve` in one terminal; `curl -X POST http://127.0.0.1:8787/run -H "Content-Type: application/json" -d '{"prompt":"Create a file ok.txt with content OK","pack":"engineering"}'`. Expect 200 and JSON with `_meta` and payload. |
| **Local LLM bootstrap (start if unreachable)** | With Ollama stopped, run `fabric run "list files" --pack engineering` (default `local_llm_ensure_available: true`). Fabric should start `ollama serve` and then run; or fail with a clear “couldn’t start or reach” message if Ollama isn’t installed. |

**Not automated (prompt/behaviour)**

- **FR5.1 / FR5.2:** Quality gates (no “works” without tests; deploy proposed only; citations only from fetch) are in system prompts; compliance is by design and manual inspection, not automated assertion.
- **FR5.3:** Research with `network_allowed: false` omits web tools (tested in test_packs); tools return “network disabled” when invoked (in tool implementation).

---

## Phase 2 checklist (from [PLAN.md](PLAN.md)) — **complete**

| # | Deliverable | Status | Notes |
|---|-------------|--------|-------|
| 2.1 | Capability model: define capabilities, map packs in config | Done | `config/capabilities.py` (CAPABILITY_KEYWORDS); `capabilities` field on SpecialistConfig; DEFAULT_CONFIG updated |
| 2.2 | Task → capabilities (rules or router model) | Done | `infer_capabilities()` in `application/recruit.py`; keyword substring matching |
| 2.3 | Recruitment: select pack(s) from capabilities (single pack for Phase 2) | Done | `RecruitmentResult`; two-stage routing in `recruit_specialist()`; keyword fallback preserved |
| 2.4 | Runlog/metadata: log required_capabilities, selected_pack(s) | Done | `"recruitment"` event in runlog; `required_capabilities` on `RunResult`; in HTTP `_meta` |
| 2.5 | Docs: VISION §8, REQUIREMENTS, STATE updated | Done | `REQUIREMENTS.md` FR2.1 rewritten; VISION §8 alignment table updated; `docs/CAPABILITIES.md` new |

---

## Phase 3 checklist (from [PLAN.md](PLAN.md)) — **complete**

| # | Deliverable | Status | Notes |
|---|-------------|--------|-------|
| 3.1 | Task decomposition outputs multiple capability IDs | Done | `infer_capabilities()` returns all matching caps; `_greedy_select_specialists()` covers all of them |
| 3.2 | Supervisor runs multiple packs; shared workspace + combined runlog | Done | `execute_task()` loops over `specialist_ids`; single run dir; `pack_start` events in runlog |
| 3.3 | Sequential coordination with context handoff | Done | finish payload from pack N forwarded as context to pack N+1; step names prefixed by specialist ID |
| 3.4 | Docs and STATE updated | Done | BACKLOG.md Phase 3 section; STATE.md; PLAN.md ticks |

---

## Phase 4 checklist (from [PLAN.md](PLAN.md)) — **complete**

| # | Deliverable | Status | Notes |
|---|-------------|--------|-------|
| 4.1 | Generic/cloud LLM client + `ModelConfig.backend` field | Done | `infrastructure/chat/__init__.py` (build_chat_client factory); `GenericChatClient` in `infrastructure/chat/generic.py`; shared `parse_chat_response()` in `_parser.py`; `backend: str = “ollama”` on `ModelConfig` |
| 4.2 | `fabric logs` CLI subcommand | Done | `logs list` (Rich table) and `logs show` (pretty-printed JSON with kind filter) in `interfaces/cli.py`; `RunSummary` + `list_runs()` + `read_run_events()` in `infrastructure/workspace/run_reader.py` |
| 4.3 | OpenTelemetry tracing (optional dep) | Done | `infrastructure/telemetry.py` (`_NoOpSpan`, `_NoOpTracer`, `setup_telemetry()`, `get_tracer()`); graceful no-op when OTEL not installed; `TelemetryConfig` in `config/schema.py`; `fabric.execute_task` / `fabric.llm_call` / `fabric.tool_call` spans in `execute_task.py`; `[otel]` extra in `pyproject.toml` |
| 4.4 | Docs update | Done | BACKLOG.md Phase 4 section; STATE.md; PLAN.md Phase 4 concrete deliverables |

---

## Phase 5 checklist (from [PLAN.md](PLAN.md)) — **complete**

| # | Deliverable | Status | Notes |
|---|-------------|--------|-------|
| 5.1 | Config schema: MCPServerConfig + mcp_servers | Done | `config/schema.py`; validators for stdio/sse; duplicate-name check |
| 5.2 | Async execute_tool + pack lifecycle (aopen/aclose) | Done | `base.py`, `ports.py`, `execute_task.py`; try/finally in _execute_pack_loop |
| 5.3 | MCPSessionManager + converter | Done | `infrastructure/mcp/session.py`, `converter.py`; top-level mcp import guarded |
| 5.4 | MCPAugmentedPack | Done | `infrastructure/mcp/augmented_pack.py`; asyncio.gather connect/disconnect |
| 5.5 | Registry integration | Done | `registry.py` wraps pack when mcp_servers non-empty; RuntimeError if mcp not installed |
| 5.6 | pyproject.toml + docs | Done | `mcp = [“mcp>=1.0”]` optional dep; dev dep updated; all docs updated |

---

## Next steps (what to do when resuming)

**The backlog is the canonical source for what to work on next.**

1. Read [BACKLOG.md](BACKLOG.md) — find the first non-done item; that is what to work on.
2. Run `pytest tests/ -k “not real_llm and not verify and not real_mcp”` — confirm **402 pass** before touching code.
3. Phase 9 is complete — see BACKLOG.md for Phase 10 planning or add new items.
4. See [DECISIONS.md](DECISIONS.md) for rationale behind key architectural choices.

---

## Quick commands (for copy-paste)

```bash
# From repo root
pip install -e ".[dev]"
pytest tests/ -v

# CLI
fabric --help
fabric run "list files" --pack engineering
fabric run "mini systematic review of X" --pack research

# API (background)
fabric serve
# then: curl http://127.0.0.1:8787/health
# POST: curl -X POST http://127.0.0.1:8787/run -H "Content-Type: application/json" -d '{"prompt":"list files","pack":"engineering"}'
```

---

## Architecture changes (2026-02-24 refactor)

The tool loop was completely reworked from a fragile JSON-in-content protocol to **native OpenAI function calling**:

- `ChatClient.chat()` now accepts `tools: list[dict] | None` and returns `LLMResponse` (not `str`)
- `LLMResponse` + `ToolCallRequest` are domain types in `domain/models.py`
- `SpecialistPack` now has `tool_definitions` and `finish_tool_name` properties
- `execute_task` runs a proper tool-calling loop; `finish_task` tool call signals completion
- `OllamaChatClient` detects “does not support tools” in 400 responses and raises a clear error
- `_param_size_sort_key` fixed: parses “8.0B” as 8.0 not 80 (was causing sqlcoder:15b to be selected over llama3.1:8b)
- `resolve_llm` is called via `asyncio.to_thread` in the FastAPI handler

## Blockers / open questions

- None at last update.

---

## Doc map (for agents)

| Read first | Then | For |
|------------|------|-----|
| **STATE.md** (this file) | BACKLOG.md | Resuming work; current phase and what’s next |
| **BACKLOG.md** | — | Prioritised work items with full context; single source of truth for "what to do next" |
| **DECISIONS.md** | — | Architectural decisions and rationale; read before changing significant design |
| PLAN.md | REQUIREMENTS.md, VISION.md | Phase deliverables, verification gates, full context |
| REQUIREMENTS.md | — | MVP functional requirements and validation |
| VISION.md | — | Long-term vision, principles, use-case pillars |

**Workflow:** When you complete an item, tick it off in BACKLOG.md and move it to the Done table.
Update STATE.md with the new date. Run the fast CI check before and after every change.
