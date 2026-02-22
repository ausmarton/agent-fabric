# agent-fabric documentation

Docs live here and in the repo root. Use this index to find the right doc for building, resuming, or validating.

---

## For resuming work (any session / agent)

1. **[STATE.md](STATE.md)** — Current phase, what’s done, what’s next, verification checklist, quick commands. **Start here.**
2. **[PLAN.md](PLAN.md)** — Iterative build plan: phases, deliverables, verification gates, resumability instructions.

---

## For product and direction

3. **[VISION.md](VISION.md)** — Long-term vision: use cases (illustrative), principles, architecture (task → recruit → task force), alignment with repo.
4. **[DESIGN.md](DESIGN.md)** — Design from first principles: fit for purpose, naming (agent_fabric), directory structure, no prototype carry-over.
5. **[../REQUIREMENTS.md](../REQUIREMENTS.md)** — MVP functional requirements and validation (manual + automated).
6. **[BACKENDS.md](BACKENDS.md)** — We are not locked to Ollama; deployment philosophy (native vs container, repeatable setup).
7. **[LLM_OPTIONS.md](LLM_OPTIONS.md)** — **Reference:** every way LLMs can run for the fabric (on-host, in-process, container, remote), with advantages, disadvantages, and when to use each.

---

## For users

8. **[../README.md](../README.md)** — Quickstart, usage, extending packs, testing.

---

## Summary

| Doc | Purpose |
|-----|--------|
| [STATE.md](STATE.md) | Where we are; what to do next; verification gate; **update when you complete work**. |
| [PLAN.md](PLAN.md) | How we build iteratively; phases and checks. |
| [VISION.md](VISION.md) | Why we’re building this; principles; alignment. |
| [DESIGN.md](DESIGN.md) | Clean-slate design: naming, structure, first principles. |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Target architecture; package layout; ports; flow. |
| [../REQUIREMENTS.md](../REQUIREMENTS.md) | What the MVP shall do; how to validate. |
| [BACKENDS.md](BACKENDS.md) | Not locked to Ollama; deployment (native vs container). |
| [LLM_OPTIONS.md](LLM_OPTIONS.md) | **Reference:** all LLM options, pros/cons, when to use. |
| [VERIFICATION_PASSES.md](VERIFICATION_PASSES.md) | **Phase 1 checklist:** multi-pass verification (fast CI, CLI, API, full validation, live demo). |
| [../README.md](../README.md) | How to install, run, and extend. |
