# Design from first principles

This document explains how the system is designed **from a clean slate** against the vision and requirements, not by refactoring the prototype. It covers: fit for purpose, naming, and directory structure.

---

## 1. Is the design fit for purpose?

**Purpose (from VISION + REQUIREMENTS):** Run user tasks by (1) choosing a specialist (routing/recruitment), (2) running one specialist in a tool loop (LLM + tools until "final"), (3) persisting run directory and runlog. Local-first, Ollama by default, quality-first.

**Design choices made from first principles:**

| Concern | Design decision | Rationale |
|--------|------------------|-----------|
| **Who runs the task?** | One specialist per run, chosen by recruitment (today: keyword over prompt). | Vision says "recruit on demand"; MVP is one pack per run. No "toggle teams"—we select who is needed. |
| **How does a run execute?** | Single loop: messages → LLM → parse response → if tool call, run tool and continue; if final, return. | One control flow, parameterised by specialist (prompt + tools). No separate "workflow" per pack; the run *is* the loop. |
| **Where do we depend on concrete I/O?** | Only in infrastructure and interfaces. Application depends on abstractions (ports). | Testability and swap (e.g. different LLM or storage) without touching use cases. |
| **Config** | Loaded at the edge (CLI/API); passed into use case and infra. Application does not read env/files. | Clear boundary; config is a dependency, not a global. |
| **Observability** | Run directory + append-only runlog per run. | Per-run audit trail; no prototype-specific "RunLogger" object—just append_event to a file. |

The prototype had: supervisor + router + per-pack "workflow" files that each contained a copy of the tool loop. The clean design has: **one** tool loop in the application, **one** recruit step, and specialists that supply only prompt + tool list + tool execution. So the design is **not** "the prototype with nicer names"; it is a single use case with ports and one loop.

---

## 2. Naming and organisation: reasoning, not assumptions

**We do not assume the product name.** The vision describes a *kind* of system (a fabric of agents, task → recruit → task force). What you *call* that product is a separate decision. The current names are one possible outcome, not "the" right answer.

### 2.1 What should the product be called?

The **product name** is whatever you want users and the repo to refer to. It doesn't have to be "agent-fabric." Possibilities: **fabric** (short), **agent-fabric** (explicit), **task-fabric** (task-focused), **orchestrator** (control-plane). Pick one that fits how you talk about the product.

### 2.2 Repo root directory name

Convention: the **repo root folder** is the **project name**. Hyphens in folder names are normal (`agent-fabric`). So **repo root name = project name** is the right way around. The name should come from "what is this project?" not from what's already there.

### 2.3 Package directory inside the repo

In Python, the **importable package** is a directory; its name becomes the import name. **Underscores** are standard (hyphens would make `import agent-fabric` invalid). So you have: **repo root** (any name, often hyphenated) and **one main package directory** (Python-safe, usually underscores). They don't have to match.

### 2.4 Is "repo agent-fabric/ with package agent_fabric/" the right way?

- **Good:** Names align (agent-fabric → agent_fabric). Clear.
- **Redundant:** Root is `agent-fabric`, main dir inside is `agent_fabric`—repetitive. Not wrong, but not minimal.
- **Alternatives:** Repo `fabric/` + package `fabric/` (short; PyPI has a "fabric" so distribution name might differ). Or repo `agent-fabric/` + package `fabric/` (no repetition, short import).

**Conclusion:** Repo `agent-fabric` and package `agent_fabric` is **valid and conventional**. It is **not** the only right way. Best depends on whether you prefer name alignment or shorter layout.

### 2.5 Recommendation

1. **Choose the product name first.** Use it for the repo root.
2. **Then choose the Python package name:** match project (e.g. `agent_fabric`) for alignment, or shorter (e.g. `fabric`) to avoid redundancy.
3. **Current state:** Repo `agent-fabric`, package `agent_fabric` is consistent. If you prefer different names, rename; the *structure* (one package dir, tests, docs, scripts at top level) stays the same.

---

## 3. Top-level directory structure (repo root)

A single-product Python repo needs: one top-level package, tests/, docs/, scripts/, pyproject.toml, README. So:

```
<repo_root>/           # name = project name (your choice)
  <package>/           # Python package (underscore name)
  tests/
  docs/
  scripts/
  pyproject.toml
  README.md
```

**What we have:** Repo root `agent-fabric/`, package **`agent_fabric`** under **`src/agent_fabric/`** (src layout), plus **`examples/`** (example config). Consistent naming: one name (agent-fabric / agent_fabric) in two spellings; single source tree under `src`.

---

## 4. Package layout (inside src/agent_fabric)

From first principles we need:

1. **Domain** — What is a task, a run, a result? No I/O.
2. **Application** — One use case: execute task (recruit → create run → tool loop). Depends only on abstractions.
3. **Infrastructure** — LLM client, run storage, tools, specialist definitions. Implements the abstractions.
4. **Interfaces** — CLI and HTTP; wire config + infra + use case.
5. **Config** — Schema and loading (env/file). Used by interfaces and infra.

So the layout is:

```
src/agent_fabric/
  domain/           # Task, RunId, RunResult; errors
  application/      # execute_task, recruit, ports
  config/           # schema, loader
  infrastructure/   # ollama, workspace, tools, specialists
  interfaces/       # cli, http_api
```

No "router", "supervisor", "workflows", or "packs" at top level—those were prototype concepts. Recruitment lives in **application/recruit**; execution in **application/execute_task**; specialist definitions in **infrastructure/specialists**.

---

## 5. What we do not carry over

- **No** `_legacy/` — All prototype code is removed. Tests and scripts use only the new paths.
- **No** top-level `config.py` — Config is the **config/** package (schema + loader).
- **No** "workflows" or "packs" as separate top-level concepts — One tool loop; specialists are "pack" + tools in **infrastructure/specialists**.
- **No** router/supervisor modules — Replaced by **recruit** + **execute_task** and ports.

---

## 6. Summary

| Question | Answer |
|----------|--------|
| Is the design fit for purpose? | Yes: one use case (execute task), recruit → run → tool loop, ports for I/O, config at the edge. |
| Designed without the prototype? | Yes: single loop, no duplicated workflows, no supervisor/router; recruitment and execution are explicit. |
| Product/repo/package name? | Repo `agent-fabric` (project); package **`agent_fabric`** under `src/agent_fabric/` (consistent: same name, hyphen vs underscore). |
| Top-level directory structure? | Correct: one package dir, tests, docs, scripts, pyproject at root. |
| Clean slate? | Legacy code removed; directory structure reflects only this design. |

**Conventions we follow (consistent naming, clear structure):**
- **Src layout:** All package code under `src/agent_fabric/`; tests and docs import the installed package. Avoids accidental imports from repo root.
- **Consistent name:** Project and package use the same name—repo `agent-fabric`, package `agent_fabric` (hyphen vs underscore for Python).
- **Example config:** `examples/` at repo root (e.g. `examples/ollama.json`), not a top-level `config/` that could be confused with the package's config module.
- **One tool loop, one recruit:** No per-pack "workflow" files; specialists supply prompt + tools only.

See **ARCHITECTURE.md** for the concrete file layout and **ENGINEERING.md** for naming and practices.
