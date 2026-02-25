# LLM backends: not locked to Ollama

The agent fabric is **not** tied to Ollama. It talks to any backend that exposes the **OpenAI chat-completions API**. For a **comprehensive review of all LLM options** (where they run, pros/cons, when each fits), see **[LLM_OPTIONS.md](LLM_OPTIONS.md)**. (`POST /v1/chat/completions` with `model`, `messages`, `temperature`, etc., and a response with `choices[0].message.content`).

---

## Repeatable deployment: same state on every machine (Kubernetes/Terraform/Helm style)

**Goal:** Like a Kubernetes project with Terraform/Helm—a **declarative, repeatable** setup so that on a **fresh machine**, one (or a few) commands bring it to the **same state** as every other machine we run on. Use the **best capabilities available on that hardware** and **perform as well as possible** on that hardware.

**Performance and containers:** Running LLMs **inside** containers often **slows inference** (GPU passthrough overhead, memory/NUMA). So we **prefer native** for the LLM when it can be cleanly managed; use containers when that keeps things cleaner (e.g. for the fabric only, with the LLM on the host).

**Current state (Ollama as default):** We can start `ollama serve` if it's not running, but we assume **Ollama is already installed** and on PATH. Installing Ollama and pulling a model are separate, OS-specific steps—so we do *not* yet have "one command from clone to same state."

**Recommended approach: declarative bootstrap on the host (LLM native)**

- **One entrypoint** (e.g. `./bootstrap.sh` or `make deploy` or a small script in the repo) that:
  - Detects **OS and hardware** (Linux/Mac/Windows; GPU type if any).
  - **Installs the right LLM backend** for that environment (Ollama, or llama.cpp server) in a **consistent, repeatable way** (same install path or package manager per OS).
  - Installs the fabric (venv, `pip install -e .`).
  - Optionally **pulls or downloads a default model** (or writes config to use an existing one).
  - Writes **config** (e.g. `base_url`, `model`, `local_llm_start_cmd`) so `concierge run` works.
- **LLM runs on the host** (no container for inference) so we get best performance and full use of GPU/drivers.
- **Idempotent:** Running the bootstrap again on an already-set-up machine should be safe and leave the same state.
- Result: clone → run bootstrap → **one command** (or two) → machine in the same state as every other; `concierge run` uses the best available hardware.

**Native vs containers**

We **prefer native** (LLM and fabric processes on the host) when it can be **cleanly managed**—so we can start and tear down without leaving clutter or mess on the system. Use **containers** when native would be hard to keep clean (e.g. conflicting dependencies, or you need isolation and are willing to run the LLM on the host with the rest in a container). In every case the aim is **clean, safe startup and teardown with no leftover state or mess**. For the LLM itself, native usually gives better performance; if we do use containers, prefer running only the fabric (CLI and HTTP API—the Python code that runs tasks and calls the LLM) in a container, with the LLM on the host and reached via `base_url`.

**Summary:** Treat deployment like **Terraform/Helm**: declarative, repeatable, one (or few) commands to reach the same state on any fresh machine, with **clean startup and teardown and no clutter**. Prefer **native** (LLM and fabric on the host) when it can be cleanly managed; use **containers** when that’s the cleaner option (e.g. fabric in a container, LLM on the host). Use the **best capabilities on that hardware** by having the bootstrap (or config) select/install the right backend and options for GPU/CPU and OS.

---

## What the code actually uses

- **Application layer** depends only on the **ChatClient** port: `async def chat(messages, model, ...) -> str`.
- The only concrete implementation in the repo is **OllamaChatClient**, which:
  - Sends HTTP `POST {base_url}/chat/completions` with standard OpenAI-format JSON.
  - Has no Ollama-specific APIs (no Ollama-native endpoints).
- **Config** is backend-agnostic: `base_url`, `model`, and optional `local_llm_start_cmd` to start the server if unreachable. Defaults point at `http://localhost:11434/v1` and Ollama model names because that’s the documented default, not because the code requires Ollama.

Alignment tests in `tests/test_backends_alignment.py` assert: application uses only `ChatClient.chat(messages, model, ...)`; config ensures local LLM by default; API calls `ensure_llm_available` when enabled and skips when `local_llm_ensure_available: false`; run dirs only under `workspace_root/runs/`.

So you can run the fabric against:

- **Ollama** (default): `ollama serve`, pull models, set nothing or use `examples/ollama.json`.
- **llama.cpp** (e.g. `llama-server` or `llama-cpp-python`): run the server with `--host` / `--port`, set `base_url` to `http://localhost:<port>/v1` and `model` to the name the server expects.
- **vLLM, LiteLLM, etc.**: same idea—expose the OpenAI-compatible endpoint and set `base_url` + `model` in config.
- **OpenAI / Azure / other cloud**: set `base_url` and `model` (and `api_key` if your config supports it). The current client sends the same request shape; you may need a thin wrapper or a second implementation that sets the right headers.

## Why Ollama is the default

- **Local-first:** Runs on the machine with a single binary; no GPU required for small models.
- **Portable:** Linux, macOS, Windows; simple install (`curl | sh` or package manager).
- **Good UX:** `ollama pull <model>`, then go; built-in OpenAI-compatible `/v1` endpoint.
- **Fits VISION:** Fedora/Linux, AMD-friendly; Ollama works with Vulkan/ROCm.

So Ollama is the **default** for local inference and docs, not a hard dependency. The most portable part is the **API contract** (OpenAI chat-completions); the default backend choice is a product decision you can override entirely via config (and, if you want, another ChatClient implementation).

## Making it explicit in code (optional)

To make portability obvious in the codebase, you could:

- Rename `OllamaChatClient` → something like `OpenAICompatibleChatClient` (and keep the old name as an alias), and rename the `ollama` package to e.g. `openai_compatible`.
- Or keep `OllamaChatClient` and add a one-line docstring: “OpenAI-compatible HTTP client; default config points at Ollama.”

Either way, the fabric stays backend-agnostic at the application layer; only config and the chosen client implementation bind you to a specific server.
