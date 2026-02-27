# Changelog

All notable changes to agentic-concierge are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [0.3.3] — 2026-02-27

### Fixed

- `scripts/verify_manual.sh`: drop `tail -1` before `grep` in the cargo-test check — the
  final line of `cargo test -q` output is an empty line, causing the check to always fail.
- `scripts/verify_manual.sh`: skip the install.sh full-run when the launcher binary is not
  yet present in the GitHub release (CI cross-compile pending), instead of marking it as FAIL.
- `scripts/verify_manual.sh`: skip the docker section when the `docker compose` plugin is
  not available (e.g. podman-docker emulation without podman-compose).

---

## [0.3.2] — 2026-02-27

### Added

**Phase 14 — Native Rust Hot Paths + macOS Support**
- `launcher/src/setup.rs`: `extract_uv()` — pure-Rust `.tar.gz` extraction using
  `flate2::read::GzDecoder` + `tar::Archive`; replaces `std::process::Command::new("tar")`
  subprocess. No system `tar` dependency required on any platform.
- `launcher/src/update.rs`: Ed25519 signed binary verification before atomic self-update.
  `verify_binary_signature_with_key()` (inner, testable with custom keys) +
  `verify_binary_signature()` (production, uses embedded `SIGNING_PUBLIC_KEY`).
  `apply_update()` now downloads `{binary_url}.sig`, verifies, cleans up on failure,
  renames only on success.  Asset names updated for macOS: `concierge-{arch}-apple-darwin`.
- `launcher/src/exec.rs`: `#[cfg(unix)]` attribute on `exec_python_concierge()`;
  comment documenting Phase 15 Windows implementation path.
- `scripts/generate_signing_key.sh`: one-time Ed25519 keypair generation helper.
  Prints public key as Rust array literal (paste into `update.rs`) and private key as PEM
  (store as CI secret `LAUNCHER_SIGNING_KEY_PEM`).
- `Cargo.toml` deps: `flate2 = "1"`, `tar = "0.4"`,
  `ed25519-dalek = { version = "2", default-features = false, features = ["std"] }`.
  All pure Rust; static musl linking unaffected.
- `.github/workflows/build-launcher.yml`: renamed `build-musl` → `build-native`; added
  `x86_64-apple-darwin` (macos-13) and `aarch64-apple-darwin` (macos-latest) targets;
  portable binary size gate using `perl -e`.
- `.github/workflows/release.yml`: `build-launcher-release` matrix extended with macOS
  targets; `Sign binaries` step signs each binary with `openssl pkeyutl -rawin` using
  `LAUNCHER_SIGNING_KEY_PEM` CI secret (graceful — warning only if secret unset).
- `install.sh`: OS+arch platform dispatch replaces Linux-only guard.
  Supports Linux x86_64/aarch64 (musl) and macOS x86_64/arm64 (apple-darwin).
- `Makefile`: `setup-rust-toolchain` target — idempotent user-local rustup install
  (no system packages; installs to `~/.cargo/`); `lint-rust` uses `~/.cargo/bin/cargo`.
- `docs/DECISIONS.md`: ADR-017 — Ed25519 signed self-update (key management, failure
  policy, rationale for Ed25519 over RSA/ECDSA/checksum).
- `docs/ARCHITECTURE.md`: Section 10 — hot-path analysis table; future evolution table
  updated to show Phase 14 deliverables as done.
- `docs/BACKLOG.md`: Phase 14 DONE; Phase 15 (Windows + Homebrew), Phase 16 (PyO3 +
  extra packs), Phase 17+ (multi-tenant, Web UI, plugin registry) future sections added.

### Changed

- `launcher/src/setup.rs`: `ensure_uv()` now calls `extract_uv()` instead of shelling
  out to `tar`. `find_file()` helper removed (no longer needed).
- `launcher/src/update.rs`: `apply_update()` extended with sig download + verification
  steps; cleanup on verification failure; atomic rename only after successful verify.

---

## [0.3.1] — 2026-02-26

Phase 13: Rust thin launcher, static musl binaries, and one-liner install script.

### Added

**Phase 13 — Rust Thin Launcher**
- `launcher/` Rust crate (`concierge-launcher v0.1.0`): static musl binary for Linux x86_64 and aarch64.
- `launcher/src/config.rs`: `LauncherConfig` struct; `CONCIERGE_DATA_DIR` env override; `CONCIERGE_NO_UPDATE_CHECK` skip-update flag; `CONCIERGE_EXTRA` pip-extras passthrough.
- `launcher/src/setup.rs`: `ensure_environment()` — system-Python detection (>=3.10), uv download fallback, venv creation, pip install; fast-path for already-installed venv. `upgrade_package()`, `installed_version()`.
- `launcher/src/update.rs`: `check_latest_release()` — GitHub Releases API; silently returns `None` on any network failure. `apply_update()` — atomic binary replacement (`rename`). `is_newer()` — semver comparison.
- `launcher/src/exec.rs`: `exec_python_concierge()` — `execv()` replaces process image; strips `--self-update` from forwarded args; correct PID and signal forwarding, no zombie launcher.
- `launcher/src/main.rs`: orchestration only; `--self-update` flag applies update + upgrades Python package then exits; passive update-hint on every run (advisory, never blocks).
- `launcher/rust-toolchain.toml`: pins `stable` channel; requires `clippy` and `rustfmt` components.
- `.github/workflows/build-launcher.yml`: CI on every push — `cargo test`, `cargo clippy -D warnings`, `cargo fmt --check`; cross-compile matrix for `x86_64-unknown-linux-musl` and `aarch64-unknown-linux-musl` via `cross`; binary size gate (< 15 MB); uploads artifacts.
- `release.yml` updated: `build-launcher-release` job cross-compiles both musl targets; `release` job attaches `concierge-x86_64-unknown-linux-musl` and `concierge-aarch64-unknown-linux-musl` to the GitHub Release (launcher failure does not block Python/Docker release).
- `install.sh`: POSIX one-liner; `curl | sh`; detects arch, downloads from GitHub Releases, atomic `mv` from tempfile; `CONCIERGE_INSTALL_DIR` override; PATH hint if dir not in PATH.

---

## [0.3.0] — 2026-02-26

Phase 12: Engineering quality gates, LLM orchestrator, and session continuation.

### Added

**Phase 12A — Engineering Quality Gates**
- `run_tests()` sandbox tool with auto-detection (pytest / cargo / npm) and structured output (`passed`, `failed_count`, `error_count`, `summary`, `output`, `framework`).
- `tests_verified` required field on the engineering pack's `finish_task` tool; the LLM must set it to `true` after a passing test run.
- `validate_finish_payload()` quality-gate hook on `BaseSpecialistPack` (no-op default); engineering pack overrides to reject `tests_verified=false` and route the LLM back to fix failures.
- Engineering system prompt updated with mandatory quality-gate instructions (run tests → verify pass → set `tests_verified=true`).

**Phase 12B — LLM Orchestrator**
- `application/orchestrator.py`: `orchestrate_task()` function decomposes a task into an `OrchestrationPlan` via a `create_plan` LLM tool call; gracefully falls back to capability-based routing on any failure.
- `OrchestrationPlan` and `SpecialistBrief` dataclasses; plan carries mode (`sequential` / `parallel`), per-specialist brief texts, synthesis flag, and reasoning.
- Brief injection in `execute_task.py`: each specialist receives its targeted sub-task description alongside the original prompt.
- `_synthesise_results()` step: when `synthesis_required=True`, a final LLM call merges all specialist outputs into a coherent summary.
- `orchestration_plan` runlog event written before execution starts.
- `concierge plan "<task>"` CLI command: preview the orchestration plan (mode, specialist assignments, briefs) without creating a run.

**Phase 12C — Session Continuation**
- `infrastructure/workspace/run_checkpoint.py`: `RunCheckpoint` dataclass with atomic save (`.tmp` + rename), `load_checkpoint`, `delete_checkpoint`, and `find_resumable_runs`.
- Checkpoint written after initial run setup and updated after each specialist completes; deleted on `run_complete`.
- `resume_execute_task()` in `execute_task.py`: loads checkpoint, skips already-completed specialists, seeds `prev_finish_payload`, and re-uses the existing pack loop.
- `find_resumable_runs(workspace_root)`: returns run IDs that have a checkpoint but no `run_complete` in the runlog.
- `concierge resume <run-id>` CLI command: shows completion status, streams events to terminal.
- `concierge logs list` now marks interrupted runs with a `(resumable)` indicator.

### Tests
- `tests/test_run_tests_tool.py` — 15 tests (auto-detection, per-framework commands, output parsing, timeout, sandbox pass-through).
- `tests/test_engineering_pack_quality.py` — 5 tests (quality gate rejects/passes, `run_tests` in tool list, `tests_verified` required).
- `tests/test_orchestrate_task.py` — 20 tests (plan parsing, brief propagation, mode selection, synthesis flag, fallback paths, `_get_brief` helper).
- `tests/test_run_checkpoint.py` — 16 tests (round-trip, atomic write, delete, `find_resumable_runs`).
- `tests/test_resume.py` — 8 tests (missing checkpoint, all-complete error, single-specialist resume, skip completed, checkpoint deletion, `run_complete` event).
- `tests/test_execute_task.py` — +4 tests (brief injection, synthesis gating, quality gate rejection, checkpoint lifecycle).

---

## [0.2.0] — 2026-02-26

Phases 10–11: self-sizing bootstrap, three-layer inference, profile-based features, browser tool, and ChromaDB vector store.

### Added

**Phase 10 — Self-sizing bootstrap and three-layer inference**
- `bootstrap/` package: `system_probe` (CPU/RAM/GPU detection), `model_advisor` (recommends model tier), `backend_manager` (starts/stops inference backends), `first_run` (interactive + non-interactive setup), `detected` (cached probe results).
- `config/features.py`: `Feature` enum, `ProfileTier` (nano/small/medium/large/server), `FeatureSet`, `PROFILE_FEATURES` mapping, `FeatureDisabledError`.
- `FeaturesConfig` and `ResourceLimitsConfig` added to `ConciergeConfig`; `profile` and `features` top-level fields.
- `InProcessChatClient` — mistral.rs in-process inference via the `[nano]` extra (`mistralrs`).
- `VLLMChatClient` — OpenAI-compatible HTTP client for vLLM (no `vllm` package dep; concurrent batching).
- `build_chat_client()` factory extended to dispatch `"vllm"` and `"inprocess"` backends.
- `concierge bootstrap [--profile PROFILE] [--non-interactive]` CLI command.
- `concierge doctor` command: Rich table of system health (backends, extras, feature availability).
- New optional dep groups: `[nano]` (mistralrs), `[embed]` (chromadb), `[browser]` (playwright).
- New core deps: `psutil>=5.9`, `platformdirs>=4.0`.

**Phase 11 — Browser tool and ChromaDB vector store**
- `infrastructure/tools/browser_tool.py`: `BrowserTool` (Playwright, `[browser]` extra); actions: `navigate`, `get_text`, `get_links`, `click`, `fill`, `screenshot`; 30 s timeout; URL validation.
- `infrastructure/workspace/run_index_chroma.py`: `ChromaRunIndex` — lazy `chromadb` import, `add()`, `search()` (cosine via ChromaDB).
- `Feature.BROWSER` added to all non-nano profiles.
- `RunIndexConfig` extended with `provider`, `chromadb_path`, `chromadb_collection` fields.
- `BaseSpecialistPack.aopen()` registers browser tools when `Feature.BROWSER` is enabled; `execute_tool()` awaits async tool coroutines.
- `MCPAugmentedPack.aopen()`/`aclose()` propagate to the inner pack.
- `SpecialistRegistry` loads detected tier → `FeatureSet` and injects `_feature_set` into packs.
- `run_index.py`: `append_to_index`/`semantic_search_index` accept `RunIndexConfig`; ChromaDB dispatch via `_resolve_chromadb_path`.
- `concierge doctor` extended: shows browser/chromadb extras availability.

---

## [0.1.0] — 2026-02-26

Initial public release of agentic-concierge, covering Phases 1–8.

### Added

**Phase 1 — MVP**
- Native OpenAI tool-calling protocol (not JSON-in-content); `finish_task` as the terminal signal.
- `engineering` specialist pack: plan → implement → test → review → iterate loop.
- `research` specialist pack: scope → search → screen → extract → synthesise → critique loop.
- CLI (`concierge run`) and HTTP API (`POST /run`) entry points.
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
- `concierge logs list` and `concierge logs show` CLI subcommands.
- OpenTelemetry tracing (optional `[otel]` dep; no-op shim when absent).

**Phase 5 — MCP tool server support**
- `MCPServerConfig` in config: stdio and SSE transports.
- `MCPAugmentedPack` wraps any specialist pack; tools discovered at `aopen()`.
- Tool names prefixed `mcp__<server>__<tool>` to avoid collisions.
- `aopen()`/`aclose()` lifecycle; `finally` block guarantees subprocess cleanup.
- Optional `[mcp]` dep group; clear `RuntimeError` if `mcp_servers` configured without the dep.

**Phase 6 — Run index, containerisation, and cloud fallback**
- Persistent cross-run index (`run_index.jsonl`); `concierge logs search <query>` CLI subcommand.
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

**Phase 9 — UX and production hardening**
- `concierge run --stream` (`-s`): real-time terminal rendering of all run events (tool calls, LLM steps, errors) using Rich.
- Corrective re-prompt recovery: when the LLM returns plain text instead of a tool call, up to 2 automatic re-prompts nudge it back on track before falling back to text-as-payload.
- Improved sandbox error messages: absolute-path violations now say "use a relative path (e.g. 'app.py')" instead of the cryptic "must be within sandbox root".
- Engineering system prompt explicitly instructs the model to use relative paths.
- Per-IP HTTP rate limiting: `CONCIERGE_RATE_LIMIT=<n>` env var (requests per minute); `GET /health` always exempt; `429 Too Many Requests` with `Retry-After` header.

### Infrastructure
- Hexagonal (ports-and-adapters) architecture: `domain` → `application` → `infrastructure` → `interfaces`.
- MIT licence; full contributor guide (`CONTRIBUTING.md`).
- GitHub Actions CI: lint (ruff), test matrix (Python 3.10/3.11/3.12), security audit (pip-audit), build check.
- Release workflow: automated PyPI publish (OIDC trusted publishing) + Docker image to GHCR on version tags.
- Dockerfile (multi-stage builder + slim runtime) and docker-compose.yml (Ollama + agentic-concierge + model-pull).

[Unreleased]: https://github.com/ausmarton/agentic-concierge/compare/v0.3.3...HEAD
[0.3.3]: https://github.com/ausmarton/agentic-concierge/compare/v0.3.2...v0.3.3
[0.3.2]: https://github.com/ausmarton/agentic-concierge/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/ausmarton/agentic-concierge/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/ausmarton/agentic-concierge/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/ausmarton/agentic-concierge/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/ausmarton/agentic-concierge/releases/tag/v0.1.0
