# Local LLM: default and core

**Local LLM (Ollama) is the default and primary path.** The fabric ensures it's available (including starting it when unreachable) **by default**. You don't have to remember to start Ollama first.

## Principle

- **Local LLM is the core**, not a fallback. We use as much of the local LLM as possible by default.
- The fabric **ensures the local LLM is available** before running: if the configured endpoint is unreachable, we start it (e.g. `ollama serve`) and wait until it's healthy. This is default behaviour.
- **Opt-out** only when you manage the server yourself: set `local_llm_ensure_available: false` in config (e.g. in CI or when Ollama runs elsewhere).

## Config

Default config already has `local_llm_ensure_available: true`. In a custom config (e.g. `CONCIERGE_CONFIG_PATH`):

```json
{
  "models": { ... },
  "specialists": { ... },
  "local_llm_ensure_available": true,
  "local_llm_start_cmd": ["ollama", "serve"],
  "local_llm_start_timeout_s": 90
}
```

- **`local_llm_ensure_available`** (default: `true`): when true, we ensure the model's `base_url` is reachable; if not, we run `local_llm_start_cmd` and poll until the server responds or timeout. Set to `false` if you manage the server yourself.
- **`local_llm_start_cmd`** (default: `["ollama", "serve"]`): command to start the local LLM server. Must be on `PATH` or a full path.
- **`local_llm_start_timeout_s`** (default: `90`): seconds to wait for the server to become ready after start.

Legacy keys `auto_start_llm`, `llm_start_cmd`, `llm_start_timeout_s` are still read and mapped to the above.

## Behaviour

1. Before building the chat client, the CLI and HTTP API check whether the configured model's `base_url` is reachable.
2. If it's reachable, we continue.
3. If it's not and `local_llm_ensure_available` is true (the default) and `local_llm_start_cmd` is set:
   - We start the process in the background (detached).
   - We poll the endpoint until it responds or `local_llm_start_timeout_s` elapses.
   - On success, we continue; on timeout or if the command is not found, the CLI exits with an error and the API returns 503 with a message that local LLM is the default and we couldn't start or reach it.

## Cloud fallback (future)

Cloud is used only when the **local model** cannot meet **quality or capability** (e.g. task needs a larger model). It is **not** used when the local server is unreachable—that case is handled by ensuring the local LLM is available (start if needed). See VISION §2 and §6.

## Requirements

- For `ollama serve`: [Ollama](https://ollama.com) installed and on `PATH`.
- The first run may need `ollama pull <model>` so the model (e.g. `qwen2.5:7b`) is available.
