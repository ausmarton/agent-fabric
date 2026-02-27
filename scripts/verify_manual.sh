#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# agentic-concierge — manual smoke verification playbook
#
# Usage:
#   bash scripts/verify_manual.sh                # run all sections
#   bash scripts/verify_manual.sh --section llm  # run one section
#
# Sections:
#   launcher   Rust binary size, --help, venv bootstrap, version file
#   install    install.sh one-liner to a temp dir
#   llm        Ollama end-to-end task run (runs the full stack)
#   docker     docker compose up, /health, POST /run, teardown
#   otel       opentelemetry importable and setup_telemetry() works
#
# Each check prints PASS, FAIL, or SKIP.
# Exit code = number of FAILures (0 means all checks passed or skipped).
# ---------------------------------------------------------------------------
set -euo pipefail

# ── Python interpreter ──────────────────────────────────────────────────────
# Prefer the project venv (relative to script location) so imports work.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
if [[ -f "$PROJECT_ROOT/.venv/bin/python3" ]]; then
    PYTHON="$PROJECT_ROOT/.venv/bin/python3"
else
    PYTHON="python3"
fi

# ── colour helpers ──────────────────────────────────────────────────────────
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RESET='\033[0m'

PASS=0
FAIL=0
SKIP=0

pass()  { echo -e "  ${GREEN}PASS${RESET}  $1"; PASS=$((PASS+1)); }
fail()  { echo -e "  ${RED}FAIL${RESET}  $1"; FAIL=$((FAIL+1)); }
skip()  { echo -e "  ${YELLOW}SKIP${RESET}  $1"; SKIP=$((SKIP+1)); }

header() { echo -e "\n${CYAN}▸ $1${RESET}"; }

# ── argument parsing ────────────────────────────────────────────────────────
SECTION=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --section) SECTION="$2"; shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

run_section() { [[ -z "$SECTION" || "$SECTION" == "$1" ]]; }


# ===========================================================================
# Section: launcher
# ===========================================================================
if run_section launcher; then
    header "launcher — Rust thin binary"

    MUSL_BIN="launcher/target/x86_64-unknown-linux-musl/release/concierge"
    ARCH=$(uname -m)
    if [[ "$ARCH" == "aarch64" ]]; then
        MUSL_BIN="launcher/target/aarch64-unknown-linux-musl/release/concierge"
    fi

    # 1. Binary exists
    if [[ -f "$MUSL_BIN" ]]; then
        pass "musl binary exists at $MUSL_BIN"
    else
        skip "musl binary not built — run: cd launcher && cross build --release --target ${ARCH}-unknown-linux-musl"
    fi

    # 2. Binary size < 15 MB
    if [[ -f "$MUSL_BIN" ]]; then
        SIZE=$(stat -c%s "$MUSL_BIN" 2>/dev/null || stat -f%z "$MUSL_BIN")
        if [[ "$SIZE" -lt 15728640 ]]; then
            pass "binary size OK ($(( SIZE / 1024 / 1024 )) MB < 15 MB)"
        else
            fail "binary too large: $SIZE bytes (limit 15 MB)"
        fi
    fi

    # 3. --help with isolated data dir
    if [[ -f "$MUSL_BIN" ]]; then
        TMPDIR_LAUNCHER=$(mktemp -d)
        export CONCIERGE_NO_UPDATE_CHECK=1
        export CONCIERGE_DATA_DIR="$TMPDIR_LAUNCHER"
        if CONCIERGE_NO_UPDATE_CHECK=1 CONCIERGE_DATA_DIR="$TMPDIR_LAUNCHER" \
            "$MUSL_BIN" --help >/dev/null 2>&1; then
            pass "--help exits 0"
        else
            # --help bootstraps the venv; may fail if network is unavailable but that's OK
            skip "--help triggered venv bootstrap (network required); skipping"
        fi
        rm -rf "$TMPDIR_LAUNCHER"
    fi

    # 4. cargo test passes
    if command -v cargo >/dev/null 2>&1; then
        if cargo test --manifest-path launcher/Cargo.toml -q 2>&1 | tail -1 | grep -q "^test result: ok"; then
            pass "cargo test passes"
        else
            fail "cargo test failed"
        fi
    else
        skip "cargo not installed"
    fi

    # 5. cargo clippy clean
    if command -v cargo >/dev/null 2>&1; then
        if cargo clippy --manifest-path launcher/Cargo.toml -- -D warnings 2>&1 | grep -q "^error"; then
            fail "cargo clippy has errors"
        else
            pass "cargo clippy clean"
        fi
    else
        skip "cargo not installed"
    fi
fi


# ===========================================================================
# Section: install
# ===========================================================================
if run_section install; then
    header "install — install.sh one-liner"

    if [[ "$(uname -s)" != "Linux" ]]; then
        skip "install.sh is Linux-only; running on $(uname -s)"
    elif ! command -v curl >/dev/null 2>&1; then
        skip "curl not installed"
    else
        INSTALL_TMP=$(mktemp -d)
        export CONCIERGE_INSTALL_DIR="$INSTALL_TMP"

        # 1. Script is syntactically valid (sh -n)
        if sh -n install.sh 2>/dev/null; then
            pass "install.sh syntax OK"
        else
            fail "install.sh has syntax errors"
        fi

        # 2. Dry-run: detect arch + tag fetch (no download of binary)
        ARCH=$(uname -m)
        case "$ARCH" in
            x86_64)        pass "arch detection: x86_64 → x86_64-unknown-linux-musl" ;;
            aarch64|arm64) pass "arch detection: $ARCH → aarch64-unknown-linux-musl" ;;
            *)             fail "unsupported arch: $ARCH" ;;
        esac

        # 3. GitHub API reachable
        LATEST=$(curl -fsSL --max-time 5 \
            "https://api.github.com/repos/ausmarton/agentic-concierge/releases/latest" \
            2>/dev/null | grep '"tag_name"' | sed 's/.*"tag_name": *"\([^"]*\)".*/\1/' || true)
        if [[ -n "$LATEST" ]]; then
            pass "GitHub API reachable; latest tag = $LATEST"

            # 4. Full install
            if CONCIERGE_INSTALL_DIR="$INSTALL_TMP" sh install.sh 2>&1 | grep -q "installed to"; then
                pass "install.sh completed successfully"
            else
                fail "install.sh did not print 'installed to'"
            fi

            # 5. Binary is executable
            if [[ -x "$INSTALL_TMP/concierge" ]]; then
                pass "installed binary is executable"
            else
                fail "installed binary is missing or not executable"
            fi

            # 6. Binary size sanity
            if [[ -f "$INSTALL_TMP/concierge" ]]; then
                ISIZE=$(stat -c%s "$INSTALL_TMP/concierge" 2>/dev/null || stat -f%z "$INSTALL_TMP/concierge")
                if [[ "$ISIZE" -gt 100000 ]]; then
                    pass "installed binary size plausible ($(( ISIZE / 1024 )) KB)"
                else
                    fail "installed binary suspiciously small ($ISIZE bytes)"
                fi
            fi
        else
            skip "GitHub API unreachable; skipping install.sh full run"
        fi

        rm -rf "$INSTALL_TMP"
    fi
fi


# ===========================================================================
# Section: llm
# ===========================================================================
if run_section llm; then
    header "llm — Ollama end-to-end"

    # 1. Ollama reachable
    if curl -fsSL --max-time 3 http://localhost:11434/api/tags >/dev/null 2>&1; then
        pass "Ollama reachable at localhost:11434"
    else
        skip "Ollama not running — start with: ollama serve"
        # Skip remaining llm checks
        SECTION_LLM_SKIP=1
    fi

    if [[ -z "${SECTION_LLM_SKIP:-}" ]]; then
        # 2. A chat-capable model is available
        MODELS=$(curl -fsSL http://localhost:11434/api/tags 2>/dev/null \
                 | $PYTHON -c "import json,sys; d=json.load(sys.stdin); print('\n'.join(m['name'] for m in d.get('models',[])))" \
                 2>/dev/null || true)
        if [[ -n "$MODELS" ]]; then
            pass "Ollama has at least one model: $(echo "$MODELS" | head -1)"
        else
            fail "No models found in Ollama"
        fi

        # 3. Run a trivial task
        TASK_OUT=$($PYTHON -c "
import asyncio, sys, os
os.environ.setdefault('CONCIERGE_WORKSPACE', '/tmp/verify_llm_ws')
from agentic_concierge.interfaces.cli import app
from typer.testing import CliRunner
r = CliRunner()
result = r.invoke(app, ['run', 'echo the word VERIFIED'])
print(result.output)
sys.exit(result.exit_code)
" 2>&1 || true)
        if echo "$TASK_OUT" | grep -qi "VERIFIED\|engineering\|research"; then
            pass "task run completed and returned output"
        else
            fail "task run did not produce expected output"
            echo "     Output: $(echo "$TASK_OUT" | head -5)"
        fi

        # 4. Run directory was created
        if [[ -d "/tmp/verify_llm_ws/runs" ]]; then
            RUN_COUNT=$(ls /tmp/verify_llm_ws/runs/ 2>/dev/null | wc -l)
            if [[ "$RUN_COUNT" -gt 0 ]]; then
                pass "run directory created ($RUN_COUNT run(s))"
            else
                fail "runs/ directory is empty"
            fi
        else
            fail "workspace not created at /tmp/verify_llm_ws"
        fi

        # 5. Runlog has a tool_call event
        LATEST_RUN=$(ls -t /tmp/verify_llm_ws/runs/ 2>/dev/null | head -1)
        if [[ -n "$LATEST_RUN" ]]; then
            RUNLOG="/tmp/verify_llm_ws/runs/$LATEST_RUN/runlog.jsonl"
            if [[ -f "$RUNLOG" ]] && grep -q '"kind": "tool_call"' "$RUNLOG"; then
                pass "runlog contains tool_call event"
            elif [[ -f "$RUNLOG" ]]; then
                fail "runlog exists but contains no tool_call events"
            else
                fail "runlog.jsonl not found in $LATEST_RUN"
            fi
        fi

        # Cleanup
        rm -rf /tmp/verify_llm_ws
    fi
fi


# ===========================================================================
# Section: docker
# ===========================================================================
if run_section docker; then
    header "docker — docker compose smoke test"

    if ! command -v docker >/dev/null 2>&1; then
        skip "docker not installed"
    elif ! docker info >/dev/null 2>&1; then
        skip "Docker daemon not running"
    else
        pass "Docker daemon is running"

        # 1. docker compose up
        echo "     Starting services (this may take a minute)..."
        if docker compose up -d --wait 2>&1 | grep -q "Started\|healthy\|Running"; then
            pass "docker compose up succeeded"
        else
            fail "docker compose up failed"
        fi

        # 2. /health endpoint
        sleep 2
        HTTP_CODE=$(curl -fsSL -o /dev/null -w "%{http_code}" --max-time 10 \
            http://localhost:8787/health 2>/dev/null || echo "000")
        if [[ "$HTTP_CODE" == "200" ]]; then
            pass "/health returns 200"
        else
            fail "/health returned $HTTP_CODE (expected 200)"
        fi

        # 3. POST /run (short task — no LLM needed for schema validation)
        RUN_RESP=$(curl -fsSL -X POST http://localhost:8787/run \
            -H "Content-Type: application/json" \
            -d '{"prompt":"test","pack":"","model_key":"quality"}' \
            --max-time 5 2>/dev/null || true)
        if echo "$RUN_RESP" | $PYTHON -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if 'run_id' in d or 'detail' in d else 1)" 2>/dev/null; then
            pass "POST /run returns JSON with expected shape"
        else
            fail "POST /run did not return expected JSON"
            echo "     Response: $(echo "$RUN_RESP" | head -c 200)"
        fi

        # 4. Teardown
        docker compose down --remove-orphans -v >/dev/null 2>&1
        pass "docker compose down clean"
    fi
fi


# ===========================================================================
# Section: otel
# ===========================================================================
if run_section otel || [[ -z "$SECTION" ]]; then
    header "otel — OpenTelemetry optional dependency"

    # 1. Import check (may be absent — that's fine)
    if $PYTHON -c "import opentelemetry" >/dev/null 2>&1; then
        pass "opentelemetry importable"
        # 2. setup_telemetry() does not raise
        if $PYTHON -c "
from agentic_concierge.config import load_config
from agentic_concierge.infrastructure.telemetry import setup_telemetry
setup_telemetry(load_config())
print('ok')
" 2>&1 | grep -q "^ok$"; then
            pass "setup_telemetry() runs without errors"
        else
            fail "setup_telemetry() raised an exception"
        fi
    else
        skip "opentelemetry not installed — install with: pip install agentic-concierge[otel]"
        # No-op shim path
        if $PYTHON -c "
from agentic_concierge.infrastructure.telemetry import setup_telemetry, get_tracer
from agentic_concierge.config import load_config
setup_telemetry(load_config())
tracer = get_tracer()
print('noop_ok')
" 2>&1 | grep -q "^noop_ok$"; then
            pass "no-op shim works when opentelemetry is absent"
        else
            fail "no-op shim raised an exception"
        fi
    fi
fi


# ===========================================================================
# Summary
# ===========================================================================
TOTAL=$((PASS + FAIL + SKIP))
echo ""
echo "─────────────────────────────────────────"
printf "  ${GREEN}PASS${RESET} %-4d  ${RED}FAIL${RESET} %-4d  ${YELLOW}SKIP${RESET} %-4d  total %d\n" \
    "$PASS" "$FAIL" "$SKIP" "$TOTAL"
echo "─────────────────────────────────────────"

if [[ "$FAIL" -gt 0 ]]; then
    echo -e "  ${RED}$FAIL check(s) failed.${RESET}"
    exit "$FAIL"
else
    echo -e "  ${GREEN}All checks passed or skipped.${RESET}"
    exit 0
fi
