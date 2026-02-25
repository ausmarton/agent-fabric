# Design assessment: is the implementation suitable?

We build **for Ollama** from scratch: Ollama is our local inference backend, not an optional extra. This doc assesses how well the implementation matches the vision and where we may need to re-think.

---

## What we want (vision)

- **Task → breakdown → capabilities → recruit task force** (only the agents needed).
- **Orchestrator** that decides what to spin up; agents/packs spun up **on demand**.
- **Local-first with Ollama** — we use Ollama for local LLM inference; cloud or other backends only where needed.
- **Quality-first**; extend to new formations and use cases over time.

---

## What we have today

| Aspect | Current state | Suitable for vision? |
| **LLM backend** | OpenAI-compatible HTTP client; **defaults are Ollama** (localhost:11434, models e.g. qwen2.5:7b / qwen2.5:14b). | **Yes.** We build for Ollama; other backends work via config override. |
| **Routing** | Keyword-based: one pack per run (engineering vs research). | **No.** No task decomposition, no capability model, no “recruit a task force.” We pick one pack, we don’t form a team from capabilities. |
| **Packs / agents** | Two packs (engineering, research), each with tools + workflow. | **Partially.** Good building block (pluggable packs, tools, runlog). But no multi-pack per run, no capability metadata, no on-demand spin-up of specialist agents. |
| **Tool use** | Model is asked to output JSON (`action: tool/final`, `tool_name`, `args`) in chat; we parse and execute. | **Fragile.** Many local models are bad at strict JSON in the middle of text. Sooner or later we should prefer **native tool/function calling** where the server supports it (e.g. OpenAI-compatible tool_calls, or Ollama’s tools API) so the model doesn’t have to emit raw JSON. |
| **Orchestrator** | Router + supervisor: pick pack, run one workflow to completion. | **No.** There is no “orchestrator” that decomposes a task, maps to capabilities, or recruits multiple agents. It’s “route once, run one pack.” |
| **Extensibility** | New pack = new file + config entry. New tool = add to pack. | **Yes.** Structure is extensible. But adding “new formations” and “task force” will need design changes (capability model, multi-run coordination). |

---

## Conclusion

- **Suitable as a first slice:** We have a working fabric built for **Ollama** (default config and quickstart). One pack per run, tools, runlog/workspace. Enough to validate the loop and run locally with Ollama.
- **Not yet suitable for the full vision:** We do not have task decomposition, capability-based recruitment, or multi-pack task forces. The architecture (packs, workflows, tools, config) is a reasonable base, but the **control plane** (how we decide who runs and how they’re composed) needs a re-think to match “recruit on demand” and “orchestrator decides what to spin up.”
- **Risks to re-think:**  
  - **Tool protocol:** Relying on “model outputs JSON in chat” is brittle; plan a path to native tool/function calling where available.  
  - **Single-pack assumption:** Workflows and supervisor are built around “one pack per run”; multi-pack will need coordination, shared context, and possibly a clearer “orchestrator” process.

---

## Ollama: what we use

We **use Ollama** for local inference. Default config points at `http://localhost:11434/v1` and Ollama model names (e.g. `qwen2.5:7b`, `qwen2.5:14b`). No extra config needed: install Ollama, `ollama serve`, `ollama pull qwen2.5:7b`, then run the fabric. To use another backend (e.g. llama.cpp), override with `CONCIERGE_CONFIG_PATH` and a config that points at that server.
