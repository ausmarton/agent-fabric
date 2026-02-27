# ---------------------------------------------------------------------------
# agentic-concierge — unified test and verification runner
#
# Usage:
#   make              → show this help
#   make test         → fast CI tests (no external services)
#   make check        → lint + fast tests
#   make test-all     → everything (Python + Rust)
#
# Individual groups:
#   make test-cli          test-sandbox     test-packs     test-orchestration
#   make test-workspace    test-bootstrap   test-config    test-routing
#   make test-streaming    test-api
#
# External-service groups (require running services):
#   make test-llm          test-real-mcp    test-podman
#   make test-browser      test-chromadb    test-launcher  test-docker
#
# Manual smoke verification:
#   make verify            (all sections)
#   make verify-launcher   verify-install   verify-llm     verify-docker
#
# Rust:
#   make test-rust         lint-rust
# ---------------------------------------------------------------------------

# Auto-detect Python: prefer project venv if present, else system python3.
PYTHON      := $(shell test -f .venv/bin/python3 && echo .venv/bin/python3 || echo python3)
PYTEST      := $(PYTHON) -m pytest
RUFF        := $(shell test -f .venv/bin/ruff && echo .venv/bin/ruff || echo ruff)
CARGO_MANIFEST := launcher/Cargo.toml

# Auto-detect cargo: prefer rustup-managed (~/.cargo/bin) over system cargo so
# that clippy/rustfmt (installed via rustup) are reachable.
CARGO       := $(shell test -f $(HOME)/.cargo/bin/cargo && echo $(HOME)/.cargo/bin/cargo || echo cargo)

# Markers excluded from the fast (CI-safe) suite
FAST_FILTER := -k "not real_llm and not real_mcp and not podman \
                    and not real_browser and not real_chromadb \
                    and not launcher and not docker"

.DEFAULT_GOAL := help

.PHONY: help
help:
	@echo ""
	@echo "  agentic-concierge test runner"
	@echo ""
	@echo "  ── Fast (CI-safe, no external services) ──────────────────────────"
	@echo "  make test             Run fast test suite (alias: test-fast)"
	@echo "  make check            lint + fast tests"
	@echo ""
	@echo "  ── Targeted fast groups ──────────────────────────────────────────"
	@echo "  make test-cli         CLI commands (CliRunner, mocked)"
	@echo "  make test-sandbox     Sandbox path + allowlist"
	@echo "  make test-packs       Specialist pack quality gates"
	@echo "  make test-routing     Capability routing"
	@echo "  make test-orchestration  Orchestrator, checkpoint, resume"
	@echo "  make test-workspace   Run index + filesystem workspace"
	@echo "  make test-bootstrap   Bootstrap, features, doctor"
	@echo "  make test-config      Config schema + loading"
	@echo "  make test-streaming   SSE streaming"
	@echo "  make test-api         HTTP API"
	@echo ""
	@echo "  ── External-service groups (require running services) ────────────"
	@echo "  make test-llm         Real LLM tests (requires Ollama)"
	@echo "  make test-real-mcp    Real MCP server (requires npx)"
	@echo "  make test-podman      Podman container isolation"
	@echo "  make test-browser     Playwright browser tool"
	@echo "  make test-chromadb    ChromaDB vector store"
	@echo "  make test-launcher    Rust launcher binary"
	@echo "  make test-docker      Docker compose integration"
	@echo ""
	@echo "  ── Combined suites ───────────────────────────────────────────────"
	@echo "  make test-local       fast + llm (no MCP/container)"
	@echo "  make test-all-python  All Python tests (no filtering)"
	@echo "  make test-rust        Rust unit tests (cargo test)"
	@echo "  make test-all         test-all-python + test-rust"
	@echo ""
	@echo "  ── Lint ──────────────────────────────────────────────────────────"
	@echo "  make lint             Ruff lint (src/ + tests/)"
	@echo "  make lint-rust        cargo fmt --check + cargo clippy"
	@echo ""
	@echo "  ── Setup ─────────────────────────────────────────────────────────"
	@echo "  make setup-rust-toolchain   Install rustup + clippy/rustfmt (user-local)"
	@echo ""
	@echo "  ── Manual smoke verification ─────────────────────────────────────"
	@echo "  make verify           All sections (requires services)"
	@echo "  make verify-launcher  Rust launcher binary smoke test"
	@echo "  make verify-install   install.sh one-liner smoke test"
	@echo "  make verify-llm       Ollama end-to-end smoke test"
	@echo "  make verify-docker    Docker compose smoke test"
	@echo ""


# ---------------------------------------------------------------------------
# Fast (CI-safe) suite
# ---------------------------------------------------------------------------

.PHONY: test test-fast
test: test-fast

test-fast:
	$(PYTEST) tests/ $(FAST_FILTER) -q


# ---------------------------------------------------------------------------
# Targeted fast groups — by file or keyword
# ---------------------------------------------------------------------------

.PHONY: test-cli
test-cli:
	$(PYTEST) tests/test_cli_commands.py tests/test_logs_cli.py -v

.PHONY: test-sandbox
test-sandbox:
	$(PYTEST) tests/test_sandbox.py -v

.PHONY: test-packs
test-packs:
	$(PYTEST) tests/test_engineering_pack_quality.py tests/test_run_tests_tool.py -v

.PHONY: test-routing
test-routing:
	$(PYTEST) tests/ -k "routing" -v

.PHONY: test-orchestration
test-orchestration:
	$(PYTEST) tests/test_orchestrate_task.py tests/test_resume.py tests/test_run_checkpoint.py -v

.PHONY: test-workspace
test-workspace:
	$(PYTEST) tests/test_run_index*.py tests/test_run_checkpoint.py -v

.PHONY: test-bootstrap
test-bootstrap:
	$(PYTEST) \
	  tests/test_features.py \
	  tests/test_system_probe.py \
	  tests/test_model_advisor.py \
	  tests/test_backend_manager.py \
	  tests/test_first_run.py \
	  tests/test_doctor_cli.py \
	  -v

.PHONY: test-config
test-config:
	$(PYTEST) tests/ -k "config" -v

.PHONY: test-streaming
test-streaming:
	$(PYTEST) tests/ -k "stream" $(FAST_FILTER) -v

.PHONY: test-api
test-api:
	$(PYTEST) tests/ -k "api" $(FAST_FILTER) -v


# ---------------------------------------------------------------------------
# External-service groups
# ---------------------------------------------------------------------------

.PHONY: test-llm
test-llm:
	$(PYTEST) tests/ -m real_llm -v

.PHONY: test-real-mcp
test-real-mcp:
	$(PYTEST) tests/ -m real_mcp -v

.PHONY: test-podman
test-podman:
	$(PYTEST) tests/ -m podman -v

.PHONY: test-browser
test-browser:
	$(PYTEST) tests/ -m real_browser -v

.PHONY: test-chromadb
test-chromadb:
	$(PYTEST) tests/ -m real_chromadb -v

.PHONY: test-launcher
test-launcher:
	$(PYTEST) tests/ -m launcher -v

.PHONY: test-docker
test-docker:
	$(PYTEST) tests/ -m docker -v


# ---------------------------------------------------------------------------
# Combined suites
# ---------------------------------------------------------------------------

.PHONY: test-local
test-local: test-fast test-llm

.PHONY: test-all-python
test-all-python:
	$(PYTEST) tests/ -v

.PHONY: test-rust
test-rust:
	$(CARGO) test --manifest-path $(CARGO_MANIFEST)

.PHONY: test-all
test-all: test-all-python test-rust


# ---------------------------------------------------------------------------
# Lint
# ---------------------------------------------------------------------------

.PHONY: lint
lint:
	$(RUFF) check src/ tests/ --select E,W,F --ignore E501,F401

.PHONY: lint-rust
lint-rust: setup-rust-toolchain
	$(HOME)/.cargo/bin/cargo fmt --manifest-path $(CARGO_MANIFEST) --check
	$(HOME)/.cargo/bin/cargo clippy --manifest-path $(CARGO_MANIFEST) -- -D warnings


# ---------------------------------------------------------------------------
# Quality gate (lint + fast tests) — run before every commit
# ---------------------------------------------------------------------------

.PHONY: check
check: lint test-fast

# ---------------------------------------------------------------------------
# Rust toolchain setup (user-local via rustup — does not touch system packages)
# ---------------------------------------------------------------------------

# Install rustup + stable toolchain + clippy + rustfmt into ~/.cargo/
# Idempotent: safe to run multiple times.
.PHONY: setup-rust-toolchain
setup-rust-toolchain:
	@if ! command -v $(HOME)/.cargo/bin/rustup >/dev/null 2>&1; then \
	  echo "[setup] Installing rustup (user-local, no sudo required)..."; \
	  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
	    | sh -s -- -y --no-modify-path --default-toolchain stable; \
	else \
	  echo "[setup] rustup already installed at $(HOME)/.cargo/bin/rustup"; \
	fi
	@$(HOME)/.cargo/bin/rustup toolchain install stable --no-self-update
	@$(HOME)/.cargo/bin/rustup component add clippy rustfmt
	@echo "[setup] Rust toolchain ready. Add to PATH: export PATH=\"$(HOME)/.cargo/bin:\$$PATH\""


# ---------------------------------------------------------------------------
# Manual smoke verification
# ---------------------------------------------------------------------------

.PHONY: verify
verify:
	@bash scripts/verify_manual.sh

.PHONY: verify-launcher
verify-launcher:
	@bash scripts/verify_manual.sh --section launcher

.PHONY: verify-install
verify-install:
	@bash scripts/verify_manual.sh --section install

.PHONY: verify-llm
verify-llm:
	@bash scripts/verify_manual.sh --section llm

.PHONY: verify-docker
verify-docker:
	@bash scripts/verify_manual.sh --section docker
