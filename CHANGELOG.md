# Changelog

All notable changes to agent-fabric are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [0.1.0] — 2026-02-25

Initial public release of agent-fabric, covering Phases 1–8.

### Added

**Phase 1 — MVP**
- Native OpenAI tool-calling protocol (not JSON-in-content); `finish_task` as the terminal signal.
- `engineering` specialist pack: plan → implement → test → review → iterate loop.
- `research` specialist pack: scope → search → screen → extract → synthesise → critique loop.
- CLI (`fabric run`) and HTTP API (`POST /run`) entry points.
- Local Ollama integration with automatic server start (`local_llm_ensure_available`).
- Sandboxed workspace per run; `finish_task` payload validation.
- Structured logging throughout; scoped exception handling in tool execution.
- Extensible specialist registry via `SpecialistConfig.builder`.
- Configurable constants (`config/constants.py`); explicit tie-breaking in specialist routing.

**Phase 2 — Capability-based routing**
- Capability model: each specialist declares `capabilities`; router scores by keyword coverage.
- Two-stage routing: prompt → required capabilities → best specialist by coverage.
- `required_capabilities` logged in runlog and returned in HTTP `_meta`.

**Phase 3 — Multi-pack task forces**
- Sequential task force: multiple specialists run in order with context handoff.
- Shared workspace and runlog across all packs in a task force.
- `pack_start` runlog events.

**Phase 4 — Observability and multi-backend LLM**
- Generic OpenAI-compatible chat client (`ModelConfig.backend`); backends: `ollama`, `openai`, `litellm`, `vllm`, `llamacpp`.
- LLM-driven orchestrator routing with keyword fallback; `routing_model_key` config.
- `finish_task` structural quality gate: requires at least one tool call before termination.
- `fabric logs list` and `fabric logs show` CLI subcommands.
- OpenTelemetry tracing (optional `[otel]` dep; no-op shim when absent).

**Phase 5 — MCP tool server support**
- `MCPServerConfig` in config: stdio and SSE transports.
- `MCPAugmentedPack` wraps any specialist pack; tools discovered at `aopen()`.
- Tool names prefixed `mcp__<server>__<tool>` to avoid collisions.
- `aopen()`/`aclose()` lifecycle; `finally` block guarantees subprocess cleanup.
- Optional `[mcp]` dep group; clear `RuntimeError` if `mcp_servers` configured without the dep.

**Phase 6 — Run index, containerisation, and cloud fallback**
- Persistent cross-run index (`run_index.jsonl`); `fabric logs search <query>` CLI subcommand.
- Real MCP filesystem server smoke test.
- Containerised workspace isolation via Podman (`ContainerisedSpecialistPack`; `:Z` SELinux label).
- Cloud LLM fallback (`FallbackPolicy`: `no_tool_calls`, `malformed_args`, `always`); `CloudFallbackConfig`; `cloud_fallback` runlog events.

**Phase 7 — Semantic search and enterprise research**
- Semantic run-index search via Ollama embeddings (`cosine_similarity`, `embed_text`).
- `enterprise_research` specialist: `cross_run_search` tool, staleness/confidence notation.
- GitHub MCP real-integration tests; `docs/MCP_INTEGRATIONS.md` with worked config examples.
- `RunIndexConfig.embedding_model` for configurable embedding model.

**Phase 8 — Parallel execution and SSE streaming**
- Parallel task force mode (`task_force_mode: parallel`); `asyncio.gather` over specialist packs.
- SSE streaming endpoint (`POST /run/stream`); `asyncio.Queue`-based event pipeline.
- `run_complete` runlog event; `GET /runs/{id}/status` endpoint.
- `_merge_parallel_payloads`: per-pack results with graceful error capture.

### Infrastructure
- Hexagonal (ports-and-adapters) architecture: `domain` → `application` → `infrastructure` → `interfaces`.
- MIT licence; full contributor guide (`CONTRIBUTING.md`).
- GitHub Actions CI: lint (ruff), test matrix (Python 3.10/3.11/3.12), security audit (pip-audit), build check.
- Release workflow: automated GitHub Release on version tags.

[Unreleased]: https://github.com/ausmarton/agent-fabric/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ausmarton/agent-fabric/releases/tag/v0.1.0
