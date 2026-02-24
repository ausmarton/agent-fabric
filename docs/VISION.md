# agent-fabric: Long-term Vision

A single, coherent vision document for the agent-fabric project. Use this to steer design and to check that the repo stays aligned with the vision.

---

## 1. Vision in one paragraph

We are building an **autonomous agentic system** that can act in many ways depending on the task. The following are **illustrative use cases**, not a fixed or comprehensive list—they help shape our **initial iterations**:

- **An engineering team** (software + data) taking ideas from development through deployment, monitoring, and fixes across cloud, local, web, and mobile.
- **A personal assistant** answering queries like “Find the best business-class tickets London–Lisbon for a week in May for two adults”, “Summarise my stocks today”, or “Tell me about RR.LSE”.
- **An enterprise research assistant** that searches Confluence, GitHub, Jira, Rally (and similar) and produces short, reasoned reports with links and explicit notes on what is likely valid vs stale.

The actual system should **eventually adapt to any new formation** required by the task: we add or recruit capabilities as needed rather than being limited to these examples.

We do **not** run every agent all the time. We **recruit on demand**: we look at the task, break it down into the capabilities required, and form a **task force** of only those agents that are needed. For example, a pure data-engineering project would not spin up mobile-app or financial-modelling specialists. The thing that is always available (or readily started) is an **orchestrator** that can decide what to spin up and get the task done—not the full roster of all possible agents. Teams are formed on demand; agents are spun up based on the specific task.

---

## 2. Principles (non‑negotiable)

- **Quality over speed**  
  We prefer precision and correctness. Where we must trade off, we choose quality.
- **Local-first**  
  Local LLM is the **default and primary** path. Prefer local models and local tooling (MCP, etc.). The fabric ensures the local LLM is available (including starting it when unreachable) by default; opt-out only for “I manage the server myself.” Use cloud only where local cannot meet quality or **capability** demands, with an explicit fallback path.
- **Portable and clean**  
  Implement in a way that stays portable and eventually supports cross‑platform use; for now, optimise for the current hardware and OS.
- **Phased and aligned**  
  Build in phases, with the full blueprint written down upfront and the design iterated as we move through phases.

---

## 3. Platform and hardware

- **OS:** Fedora Linux.
- **Local inference:** We **use Ollama** for local LLM inference. Install Ollama, pull models (e.g. qwen2.5:7b, qwen2.5:14b), run the fabric; no extra config by default.
- **Hardware (reference):** AMD Ryzen AI Max+ Pro 395, Radeon 8060S (×32), 128 GB RAM. No NVIDIA; use Vulkan/AMD-friendly runtimes (e.g. llama.cpp with appropriate backends).
- **Implication:** Build and document with Ollama as the default; other backends remain supported via config override.

---

## 4. Use-case pillars (long-term)

The examples below are **illustrative**, not exhaustive. They give concrete directions for early iterations; the goal is a system that can **adapt to whatever formation a task requires** (new capabilities, new agent types, new combinations). Not all of these need to be in the first phase.

### 4.1 Engineering (software + data)

- **Scope:** From idea → prototype → test → demo → revise (from feedback) → deploy → monitor → test, critique, and fix issues.
- **Domains:** Rust, Python, data engineering, ML/AI pipelines, Scala, GCP, autonomous pipelines and tooling, infra (e.g. Minikube, Kubernetes, GKE), Podman, JVM, SRE, testing, data quality, data provenance, modelling, architecture (including enterprise-scale).
- **Organisation:** One or more “teams” of agents; specialise where it improves accuracy, generalise where that works better. The system may use the internet when needed to gather context, like a human engineering team would.

### 4.2 Research (systematic and general)

- **Scope:** Full systematic literature review and general research (academic, professional, web).
- **Standard:** PhD‑researcher level: scoping, search, screening, extraction, synthesis, critique, with rigour and critical thinking.
- **Organisation:** As many agents as needed, structured so that rigour and traceability (screening logs, evidence tables, citations) are maintained.

### 4.3 Enterprise search and reporting

- **Scope:** Search Confluence, GitHub, Jira, Rally (and similar) for a user-defined topic; produce a short report with links and reasoning about what is valid vs potentially stale.
- **Example:** “What can you find about Supply management in our org?” → search across sources → distilled report with links and staleness/confidence notes.

### 4.4 Personal and life-assistant style queries

- **Examples:** Travel (e.g. best ticket prices, itineraries), portfolio summaries (“what’s happening today across my stocks”), instrument lookups (“Tell me about RR.LSE”).
- **Note:** May share infrastructure with research/enterprise (search, summarisation, citations) but with different tools and data sources.

### 4.5 Other specialised areas (candidate)

- Financial planning and investment optimisation.
- Open source: find issues, implement fixes, contribute back.
- Learning: organise learning goals and find/resources to support them.
- Social / trends: track social media trends with a dedicated agent ecosystem.

We can start with a small set of very specialised pillars (e.g. engineering + research) and add others incrementally.

---

## 5. Architecture and resource model

- **Specialist pool:** Many agents, each with distinct capabilities (A, B, C, D, …)—e.g. data engineering, mobile, financial modelling, research, enterprise search. None of them need to be “always on”.
- **Task → breakdown → recruit → task force:** For each task we (1) look at what’s required, (2) break it down into explicit capabilities, (3) recruit only the agents that have those capabilities, and (4) spin them up to form a **task force** for that problem. Example: pure data-engineering work → recruit data-engineering (and any supporting) agents only; no mobile-app or financial-modelling agents.
- **Orchestrator, not full roster:** What is always available (or quickly started) is something that can **decide what to spin up** and orchestrate the task—not the entire set of agents. So we don’t “toggle” which pre-defined team is active; we **form a team on demand** and spin up only what that task needs.
- **Single fabric, multiple packs:** One agent-fabric with many “packs” (capability areas). The orchestrator/router analyses the task, maps it to required capabilities, and recruits the right pack(s) or sub-agents. The system is designed to **adapt to any new formation** the task demands—new capability areas and new combinations can be added without being limited to a fixed set of use cases. The current repo uses “one pack per run” chosen by a router; the long-term model extends this to task decomposition and **multi-pack recruitment** so that the right task force is assembled and started for each request.

---

## 6. Technical direction

- **Models:** We use **Ollama** for local models by default; aim for quality and correctness on par with strong cloud models for the tasks we support. Ensuring the local LLM is available (including starting it when unreachable) is **default behaviour**. Explicit **cloud fallback** only when the local **model** cannot meet the bar (quality or capability), not when the server is unreachable.
- **Automation and tools:** MCP and other local automation; enterprise connectors (Confluence, Jira, GitHub, Rally) via MCP or custom tools, least‑privilege and sandboxed where possible.
- **Observability:** Export traces (e.g. OpenTelemetry) and maintain runlogs and audit trails so we can verify behaviour and debug.
- **Deployment and safety:** Deploy/push and other high-impact actions are proposed for human approval, not executed automatically by default.

**Cloud fallback (future).** When we add cloud support, it will be used only when the **local model** cannot meet **quality or capability** (e.g. task needs a model we don’t have locally, or the local model fails a quality bar). It will **not** be used when the local server is unreachable—that case is handled by ensuring the local LLM is available (start if needed). Implementation will be explicit (e.g. capability or quality check, or user choice), not “connection failed → try cloud”.

---

## 7. Phasing and blueprint

- **Phase 1 (current MVP):**  
  - Engineering pack: plan → implement → test → review → iterate; quality gates (no “it works” without tests/build); deploy/push proposed only.  
  - Research pack: systematic-review style workflow (scope → search → screen → extract → synthesize); screening log, evidence table, citations; no citation without fetch.  
  - Router picks pack by prompt (keyword-based or explicit `--pack`).  
  - Local OpenAI-compatible LLM only; no MCP/enterprise/observability yet.
- **Later phases (blueprint):**  
  - Task decomposition and router (e.g. small model + JSON schema) to map a task → required capabilities → which pack(s) to recruit.  
  - Containerised workers (e.g. Podman) per specialist role, spun up on demand.  
  - MCP tool servers for Confluence/Jira/GitHub (and similar).  
  - Persistent vector store for enterprise RAG (metadata, staleness).  
  - Observability export (e.g. OpenTelemetry).  
  - Cloud fallback; multi-pack recruitment so a task force (multiple agents/packs) is assembled and started per task as needed.

The full blueprint is reflected in README “Next upgrades”, REQUIREMENTS.md “Out of scope”, and this document.

---

## 8. Alignment with the repo (how to “follow the vision”)

Use this checklist to keep the repo aligned with the vision.

| Vision element | Where it lives in repo | Status / notes |
|----------------|------------------------|----------------|
| Quality over speed | README, REQUIREMENTS (quality gates), workflow system prompts | Enforced in engineering/research rules and FR5. |
| Local-first | Config `base_url`, `local_llm_ensure_available` (default True), README quickstart | Local LLM is default and primary; fabric ensures available (start if needed) by default. Cloud when local capability/quality insufficient (future). |
| Cloud fallback | Not implemented | When local **model** cannot meet quality or capability (e.g. task needs larger model), not when connection fails. Future. |
| Engineering pack: plan→implement→test→review | `workflows/engineering_v1.py`, `packs/engineering.py` | Implemented; deploy/push proposed only (FR5.1). |
| Research pack: systematic review, citations, screening | `workflows/research_v1.py`, `packs/research.py` | Implemented; citations only from fetch_url (FR5.2). |
| Deploy/push require human approval | Engineering system rules, FR5.1, `require_human_approval_for` in config | In rules and config; not auto-executed. |
| Task-based recruitment (one pack per run) | `application/recruit.py`, `config/capabilities.py`, `config/schema.py` | **Phase 2 complete:** two-stage capability routing (prompt → required capabilities → pack by coverage); `required_capabilities` logged in runlog and HTTP `_meta`; one pack per run; multi-pack task force is Phase 3. |
| Orchestrator decides what to spin up | Router today; no task decomposition yet | Vision: orchestrator always available; agents spun up on demand. No “toggle teams”. |
| Enterprise (Confluence/Jira/GitHub/Rally) | README “later”, REQUIREMENTS “out of scope” | Planned; MCP/custom tools in “Next upgrades”. |
| Observability | README “Next upgrades”, REQUIREMENTS “out of scope” | Runlog exists; OpenTelemetry export is future. |
| AMD / Fedora / Vulkan-friendly | README Quickstart (Fedora, Option A llama.cpp) | Documented; no NVIDIA assumption. |
| Portable, clean, extensible | Structure: packs, workflows, tools, config | Packs and workflows are pluggable; config-driven. |
| Phased build, blueprint upfront | README “Next upgrades”, REQUIREMENTS, this doc | Blueprint in docs; implementation follows phases. |

When adding features or refactoring, check this table and the principles in §2 to ensure the repo continues to follow the vision.
