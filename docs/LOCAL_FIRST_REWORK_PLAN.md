# Local-first rework plan

**Purpose:** Align implementation with the actual requirement: **local LLM is the default and core functionality**. We ensure the local LLM is available (including starting it) by default. Cloud is a **capability fallback** when local is insufficient—not a fallback when the server isn’t running.

---

## 1. What was wrong

| Wrong framing | Correct framing (VISION + REQUIREMENTS) |
|---------------|----------------------------------------|
| “Optional: spin up LLM if unreachable” (`auto_start_llm: false`) | **Local LLM is the primary path.** We ensure it’s available (start if needed) **by default**. |
| “Fallback” = “when connection fails, optionally start local” | **Fallback** = “when **local capability/quality** is insufficient, use cloud.” Connection failure is not “fall back to cloud”—it’s “ensure local is running.” |
| Ensuring local LLM is available is an add-on | Ensuring local LLM is available is **core behaviour**; opt-out only for “I manage the server myself.” |

**VISION §2:** “Local-first — Prefer local models and local tooling. Use cloud only where local cannot meet quality or **capability** demands, with an explicit fallback path.”

**VISION §6:** “We use Ollama for local models **by default**; … Explicit **cloud fallback** where local cannot meet the bar.” (i.e. bar = quality/capability, not “is the process running”.)

---

## 2. Principles to enforce

1. **Local LLM is the default and core.** Default config and code path assume we run on a local LLM (Ollama). No “try cloud first” or “optional local.”
2. **We ensure local LLM is available by default.** Before using the LLM we check reachability; if unreachable we **by default** try to start it (e.g. `ollama serve`) and wait for readiness. This is not a “fallback”—it’s the **primary path**.
3. **Opt-out, not opt-in.** The only opt-out is “I will manage the server myself” (e.g. `ensure_local_llm_available: false` in config or env), for environments where the user already runs Ollama or doesn’t want the fabric to start it.
4. **Cloud fallback is separate and future.** “Cloud fallback” means: when the **local model** cannot meet quality or capability (e.g. task needs a larger model or API-only capability), then use cloud. It does **not** mean “connection to local failed → try cloud.” We do not conflate “ensure local is running” with “fall back to cloud.”

---

## 3. Task breakdown (verifiable, in order)

Each task ends with a **Verification** line so you can confirm before moving on.

---

### Task A: Document the principle (no code change)

**Goal:** Single source of truth for “local = default and core; ensure available by default; cloud = capability fallback.”

- **A.1** In `docs/VISION.md` §8 (alignment table), update the “Local-first” row to state explicitly: “Local LLM is the **default and primary** path; fabric ensures local LLM is available (start if needed) by default. Cloud is used only when local **capability/quality** is insufficient (future).”
- **A.2** In the same table, update the “Cloud fallback” row to: “When **local model** cannot meet quality or capability (e.g. task needs larger model), not when connection fails. Not yet implemented.”
- **A.3** Add a short subsection under §2 (Principles) or §6 (Technical direction) that states: “Ensuring the local LLM is available (including starting it when unreachable) is **default behaviour**, not an optional feature; opt-out for managed/server-only environments.”

**Verification:** Grep/docs read confirms the three edits; no behavioural change yet.

---

### Task B: Config schema and defaults

**Goal:** Config expresses “local LLM is primary; ensure available by default” and allows opt-out.

- **B.1** Introduce a clear **local LLM** section in config (or top-level fields with clear naming):
  - `local_llm_ensure_available: bool = True` — when True (default), before using the model we ensure the endpoint is reachable and, if not, run `local_llm_start_cmd` and wait for readiness.
  - `local_llm_start_cmd: List[str] = ["ollama", "serve"]` — command to start the local LLM server.
  - `local_llm_start_timeout_s: int = 90` — seconds to wait for server readiness after start.
- **B.2** Remove or replace the current “optional add-on” naming: drop `auto_start_llm` (opt-in) in favour of `local_llm_ensure_available` (default True). Keep backward compatibility in loader if needed: if config has `auto_start_llm: true` → treat as `local_llm_ensure_available: true`; if `auto_start_llm: false` → `local_llm_ensure_available: false`; if neither present, default True.
- **B.3** Set `DEFAULT_CONFIG` so that `local_llm_ensure_available` is `True` and `local_llm_start_cmd` / `local_llm_start_timeout_s` have the above defaults.

**Verification:** `pytest tests/test_config.py -v` passes; default config has `local_llm_ensure_available is True`; loading a config file with the new keys works.

---

### Task C: Bootstrap behaviour is default, not optional

**Goal:** CLI and API **always** run “ensure local LLM available” when config says so (default True); no “if opt-in then do it.”

- **C.1** In CLI and HTTP API: before building the chat client, call `ensure_llm_available(...)` **when** `config.local_llm_ensure_available` is True (and we have a start command). Do **not** gate on an “opt-in” flag; gate only on “ensure available” being True and endpoint being the local one (or all default model endpoints for now).
- **C.2** Use the new config field names (`local_llm_ensure_available`, `local_llm_start_cmd`, `local_llm_start_timeout_s`) in code. Remove use of `auto_start_llm` in favour of `local_llm_ensure_available`.
- **C.3** Error messages: phrase as “Local LLM (Ollama) is the default; we couldn’t start or reach it.” Not “optional start failed.”

**Verification:** With default config, `concierge run "list files" --pack engineering` (with Ollama not running) either starts Ollama and proceeds, or fails with a clear “local LLM” message. With `local_llm_ensure_available: false`, fabric does not start the server and fails at first LLM call as today. `pytest tests/ -v` passes.

---

### Task D: Docs and examples

**Goal:** All user- and developer-facing text reflects “local = default and core; we ensure it’s available; cloud = capability fallback.”

- **D.1** Rewrite `docs/SELF_CONTAINED_LLM.md` so that:
  - The title/lead state that **local LLM is the default and core**; the fabric ensures it’s available (including starting it) by default.
  - Config is described as `local_llm_ensure_available` (default True), with opt-out for “I manage the server myself.”
  - No use of “optional” or “fallback” for “starting the local server”—that’s the primary path.
- **D.2** Update `REQUIREMENTS.md` (and README if needed) so that:
  - “Local inference” and “Ollama” are described as the **default and primary**; “ensure local LLM available (start if needed)” is default behaviour; cloud is explicitly “when local capability/quality is insufficient (future).”
- **D.3** Update `examples/ollama.json` (and any other example configs) to use `local_llm_ensure_available: true` (or omit so default applies) and the new field names; remove `auto_start_llm`.

**Verification:** Read-through of SELF_CONTAINED_LLM.md, REQUIREMENTS, README, and example config; no “optional local” or “fallback = start server” framing.

---

### Task E: Tests

**Goal:** Tests assert the correct defaults and behaviour; no tests assume “ensure available” is opt-in.

- **E.1** In `tests/test_config.py`: assert that default config has `local_llm_ensure_available is True`; add or update a test that loads config with `local_llm_ensure_available: false` and one with `true`.
- **E.2** In `tests/test_llm_bootstrap.py`: keep existing unit tests for `ensure_llm_available` and reachability; no change to behaviour of the bootstrap module itself unless we rename for clarity (e.g. ensure the function is clearly “ensure local LLM available” in docstrings).
- **E.3** If any integration or CLI test mocks “opt-in” behaviour, change it to “ensure available = True by default” and verify that the code path that calls `ensure_llm_available` is exercised when config has default (True).

**Verification:** `pytest tests/ -v` passes; test_config and test_llm_bootstrap reflect new defaults and names.

---

### Task F: STATE and PLAN alignment

**Goal:** STATE.md and PLAN.md describe local-first and “ensure local available by default” correctly; no deliverable says “optional bootstrap.”

- **F.1** In `docs/STATE.md`: update the row for “Self-contained LLM” / “LLM bootstrap” to say that **local LLM is the default and core**; ensuring it’s available (including start) is **default behaviour**; config is `local_llm_ensure_available` (default True), opt-out for managed environments.
- **F.2** In `docs/PLAN.md`: if Phase 1 or any deliverable mentions “optional” auto-start or “fallback” for starting the LLM, change wording to “ensure local LLM available by default (opt-out for managed server).”

**Verification:** Grep for “optional” and “fallback” in STATE and PLAN in the context of local LLM; only “cloud fallback (capability)” remains.

---

### Task G: Cloud fallback (design only, no implementation)

**Goal:** Reserve the right design for future “cloud fallback” so it’s never confused with “ensure local running.”

- **G.1** Add a short “Cloud fallback (future)” subsection in `docs/VISION.md` or `docs/PLAN.md` that states:
  - Cloud fallback is used when the **local model** cannot meet **quality or capability** (e.g. task requires a model we don’t have locally, or quality bar not met).
  - It is **not** used when the local server is unreachable or not running—that case is “ensure local LLM is available (start if needed).”
  - Implementation will be explicit (e.g. capability check, or user choice), not “connection failed → try cloud.”

**Verification:** Doc exists and is consistent with §2 and §6 of VISION.

---

## 4. Order of execution and checks

1. **A** → B → C → D → E → F → G.  
   (A is docs-only; B–C are code + config; D–F are docs + tests; G is design doc.)
2. After **B**: run `pytest tests/test_config.py -v`.
3. After **C**: run `pytest tests/ -v`; optionally run `concierge run "list files" --pack engineering` with and without Ollama to confirm behaviour.
4. After **E**: run full `pytest tests/ -v`.
5. After each of **D, F, G**: quick read/grep to confirm wording.

---

## 5. Summary

| Before | After |
|--------|--------|
| “Optional: start LLM if unreachable” (`auto_start_llm: false`) | **Local LLM is primary;** we **ensure it’s available by default** (`local_llm_ensure_available: true`); opt-out only for “I manage the server.” |
| Unclear what “cloud fallback” means | **Cloud fallback** = when local **capability/quality** is insufficient (future). Not “connection failed → cloud.” |
| Ensuring local is running feels like an add-on | Ensuring local is running is **core behaviour**; naming and docs say so. |

This plan is intended to be executed step by step with verification after each task so we get the design and implementation right.
