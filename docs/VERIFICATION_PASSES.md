# Phase 1 verification passes

Run these passes to ensure Phase 1 is working and you can demonstrate and use the system. Use them as a repeatable checklist.

---

## Pass 1: Fast CI (no LLM required)

**Goal:** All unit and integration tests that do not need a real LLM pass.

```bash
pip install -e ".[dev]"
FABRIC_SKIP_REAL_LLM=1 pytest tests/ -v
```

**Expected:** 38 passed, 4 skipped (the 4 real-LLM E2E tests skip).

**If this fails:** Fix failing tests before proceeding.

---

## Pass 2: CLI and run-dir creation (no LLM required)

**Goal:** CLI help works; a run creates a run directory with `runlog.jsonl` and `workspace/` even when the LLM is unreachable.

1. **CLI help:**
   ```bash
   fabric --help
   fabric run --help
   fabric serve --help
   ```
   Expected: help text for each command.

2. **Run dir creation:** Use a config that does not start an LLM (so the run fails fast at connection). Example: create a JSON config with `local_llm_ensure_available: false` and `base_url` pointing at an unreachable port (e.g. `http://127.0.0.1:19999/v1`). Then:
   ```bash
   export FABRIC_CONFIG_PATH=/path/to/that/config.json
   export FABRIC_WORKSPACE=/tmp/fabric_verify_ws
   rm -rf /tmp/fabric_verify_ws
   fabric run "list files" --pack engineering
   ```
   Expected: exit code 1 (connection error). Check:
   - `$FABRIC_WORKSPACE/runs/` contains one run directory (e.g. `20260223-171146-xxxxx`).
   - That directory contains `runlog.jsonl` and `workspace/`.

**If this fails:** Check config loading and that `execute_task` is invoked (run dir is created at the start of the task).

---

## Pass 3: API health and POST /run behaviour (no LLM required)

**Goal:** API serves; `/health` returns 200; `POST /run` without a working LLM returns 503.

1. Start the API (in one terminal): `fabric serve`
2. In another terminal:
   ```bash
   curl -s http://127.0.0.1:8787/health
   ```
   Expected: `{"ok":true}` and HTTP 200.

3. **POST /run** (no LLM or unreachable LLM):
   ```bash
   curl -s -X POST http://127.0.0.1:8787/run -H "Content-Type: application/json" -d '{"prompt":"hi","pack":"engineering"}'
   ```
   Expected: HTTP 503 and a JSON detail message about the LLM being unreachable or not started.

**If this fails:** Check that the API starts and that `ensure_llm_available` or the first LLM call results in 503 when the server is down.

---

## Pass 4: Full validation (real LLM required)

**Goal:** All 42 tests run and pass, including the real-LLM E2E tests. This is required to claim the system is integrated and working.

**Prerequisite:** Ollama (or another OpenAI-compatible server) running and at least one model available. For default config: `ollama serve` and `ollama pull qwen2.5:7b` (or `qwen2.5:14b`). If you use another model, set `FABRIC_CONFIG_PATH` to a config that has that model.

```bash
python scripts/validate_full.py
```

**Expected:** Exit code 0; all 42 tests run (no skips); all pass.

**If this fails:**
- "LLM not reachable" or "could not ensure LLM": start the server and pull the model, or set `local_llm_ensure_available: false` and run the server yourself.
- "4 test(s) were skipped": the configured model is not available (e.g. 404). Pull the model or point config at a model you have.
- Some test fails: fix the failing test or the implementation.

---

## Pass 5: Live demo (real LLM required)

**Goal:** Run a real task via CLI and (optionally) via API to demonstrate the system end-to-end.

1. **Single E2E script:**
   ```bash
   python scripts/verify_working_real.py
   ```
   Expected: exit 0; output says "OK: Run completed", "tool_call(s)", and "Workspace has file(s): ...".

2. **CLI run:**
   ```bash
   fabric run "Create a file hello.txt with content Hello World. Then list the workspace." --pack engineering
   ```
   Expected: run completes; JSON output with `"action": "final"` and artifacts; run dir path printed. Inspect `.fabric/runs/<id>/workspace/` for `hello.txt` and `runlog.jsonl` for `tool_call` / `tool_result` events.

3. **API run (optional):** With `fabric serve` running in another terminal:
   ```bash
   curl -s -X POST http://127.0.0.1:8787/run -H "Content-Type: application/json" -d '{"prompt":"Create a file ok.txt with content OK","pack":"engineering"}' | jq .
   ```
   Expected: HTTP 200; JSON with `_meta` and payload; `action` is `final`.

---

## Summary

| Pass | Requires LLM? | What it checks |
|------|----------------|-----------------|
| 1 | No | Fast CI: 38 tests pass, 4 skip |
| 2 | No | CLI help; run dir and runlog/workspace created |
| 3 | No | API health 200; POST /run → 503 when no LLM |
| 4 | **Yes** | Full validation: all 42 tests run and pass |
| 5 | **Yes** | Live demo: verify_working_real.py and fabric run complete successfully |

Run passes 1–3 anytime (e.g. in CI without an LLM). Run passes 4 and 5 when you have a real LLM and model available to demonstrate and use the system end-to-end.
