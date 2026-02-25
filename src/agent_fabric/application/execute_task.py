"""Execute task use case.

Flow: recruit specialist(s) → create run → for each specialist, run a tool
loop until finish_task or max_steps; context from earlier packs is forwarded
to later packs so the task force shares progress (sequential mode), or all
packs run concurrently with the same initial prompt (parallel mode).

Dependencies are injected (ports only); this module never imports from
``infrastructure`` or ``interfaces``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from agent_fabric.config import FabricConfig, ModelConfig
from agent_fabric.config.constants import MAX_LLM_CONTENT_IN_RUNLOG_CHARS
from agent_fabric.domain import RecruitError, RunId, RunResult, Task
from agent_fabric.application.ports import ChatClient, RunRepository, SpecialistRegistry
from agent_fabric.application.recruit import llm_recruit_specialist, recruit_specialist, RecruitmentResult
from agent_fabric.infrastructure.telemetry import get_tracer

logger = logging.getLogger(__name__)


_FINISH_TOOL_RESULT_CONTENT = json.dumps({"ok": True, "status": "task_completed"})


def _emit(
    queue: Optional[asyncio.Queue],
    kind: str,
    data: Dict[str, Any],
    step: Optional[str] = None,
) -> None:
    """Put a run event to the streaming queue (no-op when queue is None or full)."""
    if queue is None:
        return
    try:
        queue.put_nowait({"kind": kind, "data": data, "step": step})
    except asyncio.QueueFull:
        logger.debug("event_queue full; dropping event kind=%s", kind)


async def execute_task(
    task: Task,
    *,
    chat_client: ChatClient,
    run_repository: RunRepository,
    specialist_registry: SpecialistRegistry,
    config: FabricConfig,
    resolved_model_cfg: Optional[ModelConfig] = None,
    max_steps: int = 40,
    event_queue: Optional[asyncio.Queue] = None,
) -> RunResult:
    """Execute a task end-to-end.

    1. Recruit specialist(s) (keyword-based if not set on ``task``).
    2. Create a run directory + workspace.
    3. For each specialist, run a tool loop until ``finish_task`` or
       ``max_steps`` is reached.  When multiple specialists are recruited
       (a task force), the finish payload from each pack is forwarded as
       context to the next pack.
    4. Return a ``RunResult`` with the run id, paths, and final payload.

    Args:
        task: Prompt, optional specialist override, model key, and network flag.
        chat_client: LLM interface (``ChatClient`` port).
        run_repository: Creates run dirs and appends log events (``RunRepository`` port).
        specialist_registry: Resolves pack by id (``SpecialistRegistry`` port).
        config: Fabric configuration (models, specialists, flags).
        resolved_model_cfg: Pre-resolved model config (e.g. from ``resolve_llm``).
            Falls back to ``config.models[task.model_key]`` when not provided.
        max_steps: Maximum LLM turns *per specialist* before aborting.
        event_queue: Optional asyncio.Queue for real-time event streaming (P8-2).
            When provided, every run-log event is also put to this queue so callers
            (e.g. the SSE HTTP endpoint) can forward events in real-time.
            A sentinel ``{"kind": "_run_done_", ...}`` or ``{"kind": "_run_error_", ...}``
            is put when execution finishes.  When ``None`` (default), no queue interaction.

    Returns:
        ``RunResult`` with payload set to the arguments of the final pack's
        ``finish_task`` call (plus ``action: "final"``), or a timeout payload
        if ``max_steps`` is reached for the last specialist.

    Raises:
        RecruitError: When a specialist id is not found in config.
    """
    # --- cloud fallback wrapping -------------------------------------------------
    # When cloud_fallback is configured, wrap the injected chat_client so each
    # LLM call first tries the local model and re-issues to cloud when the policy
    # triggers.  Absence of cloud_fallback config leaves chat_client unchanged.
    if config.cloud_fallback:
        cloud_cfg = config.models.get(config.cloud_fallback.model_key)
        if cloud_cfg is None:
            logger.warning(
                "cloud_fallback.model_key %r not found in config.models; cloud fallback disabled",
                config.cloud_fallback.model_key,
            )
        else:
            from agent_fabric.infrastructure.chat import build_chat_client
            from agent_fabric.infrastructure.chat.fallback import FallbackChatClient, FallbackPolicy
            cloud_client = build_chat_client(cloud_cfg)
            policy = FallbackPolicy(config.cloud_fallback.policy)
            chat_client = FallbackChatClient(chat_client, cloud_client, cloud_cfg.model, policy)
            logger.debug(
                "Cloud fallback enabled: policy=%s cloud_model=%s",
                config.cloud_fallback.policy, cloud_cfg.model,
            )

    # --- recruit -----------------------------------------------------------------
    model_cfg = resolved_model_cfg or config.models.get(task.model_key) or config.models["quality"]

    if task.specialist_id:
        specialist_ids: List[str] = [task.specialist_id]
        required_capabilities: List[str] = []
        routing_method = "explicit"
    else:
        routing_cfg = config.models.get(config.routing_model_key)
        if routing_cfg is None:
            logger.warning(
                "routing_model_key %r not in config.models; using task model %r for routing",
                config.routing_model_key, model_cfg.model,
            )
            routing_cfg = model_cfg
        recruitment: RecruitmentResult = await llm_recruit_specialist(
            task.prompt, config,
            chat_client=chat_client,
            model=routing_cfg.model,
        )
        specialist_ids = recruitment.specialist_ids
        required_capabilities = recruitment.required_capabilities
        routing_method = recruitment.routing_method

    for sid in specialist_ids:
        if sid not in config.specialists:
            raise RecruitError(f"Unknown specialist: {sid!r}")

    # --- setup -------------------------------------------------------------------
    run_id, run_dir, workspace_path = run_repository.create_run()
    is_task_force = len(specialist_ids) > 1
    logger.info(
        "Task started: specialists=%s run_id=%s task_force=%s",
        specialist_ids, run_id.value, is_task_force,
    )

    # Log recruitment event — include both singular and plural keys for compat.
    _recruitment_event = {
        "specialist_id": specialist_ids[0],   # Phase 2 compat: primary specialist
        "specialist_ids": specialist_ids,       # Phase 3: full task force list
        "required_capabilities": required_capabilities,
        "routing_method": routing_method,
        "is_task_force": is_task_force,
    }
    run_repository.append_event(run_id, "recruitment", _recruitment_event, step=None)
    _emit(event_queue, "recruitment", _recruitment_event)

    # --- pack loop ---------------------------------------------------------------
    tracer = get_tracer()
    final_payload: Dict[str, Any] = {}
    task_force_mode = config.task_force_mode if is_task_force else "sequential"

    with tracer.start_as_current_span("fabric.execute_task") as root_span:
        root_span.set_attribute("run_id", run_id.value)
        root_span.set_attribute("specialist_ids", ",".join(specialist_ids))
        root_span.set_attribute("is_task_force", is_task_force)
        root_span.set_attribute("routing_method", routing_method)
        root_span.set_attribute("task_force_mode", task_force_mode)

        if task_force_mode == "parallel" and len(specialist_ids) > 1:
            # Parallel: all packs run concurrently; each gets the original prompt.
            # No inter-pack context forwarding.
            tf_event = {
                "specialist_ids": specialist_ids,
                "mode": "parallel",
            }
            run_repository.append_event(run_id, "task_force_parallel", tf_event, step=None)
            _emit(event_queue, "task_force_parallel", tf_event)
            logger.info(
                "Task force PARALLEL: specialists=%s run_id=%s",
                specialist_ids, run_id.value,
            )
            final_payload = await _run_task_force_parallel(
                specialist_ids=specialist_ids,
                task=task,
                workspace_path=workspace_path,
                model_cfg=model_cfg,
                chat_client=chat_client,
                run_repository=run_repository,
                run_id=run_id,
                max_steps=max_steps,
                tracer=tracer,
                event_queue=event_queue,
                specialist_registry=specialist_registry,
            )

        else:
            # Sequential: each pack receives context from the previous pack (P3 behaviour).
            prev_finish_payload: Optional[Dict[str, Any]] = None

            for pack_idx, specialist_id in enumerate(specialist_ids):
                pack = specialist_registry.get_pack(specialist_id, workspace_path, task.network_allowed)

                if is_task_force:
                    pack_start_ev = {"specialist_id": specialist_id, "pack_index": pack_idx}
                    run_repository.append_event(run_id, "pack_start", pack_start_ev, step=None)
                    _emit(event_queue, "pack_start", pack_start_ev)
                    logger.info(
                        "Task force SEQUENTIAL: starting pack %d/%d specialist=%s run_id=%s",
                        pack_idx + 1, len(specialist_ids), specialist_id, run_id.value,
                    )

                # Build initial messages for this pack.
                if prev_finish_payload is None:
                    user_content = f"Task:\n{task.prompt}"
                else:
                    prev_specialist_id = specialist_ids[pack_idx - 1]
                    context_block = json.dumps(prev_finish_payload, indent=2, ensure_ascii=False)
                    user_content = (
                        f"Task:\n{task.prompt}\n\n"
                        f"Context from '{prev_specialist_id}' specialist "
                        f"(prior task-force member):\n{context_block}"
                    )

                messages: List[Dict[str, Any]] = [
                    {"role": "system", "content": pack.system_prompt},
                    {"role": "user", "content": user_content},
                ]

                # Use pack-prefixed step names for task forces so the runlog clearly
                # shows which pack each step belongs to.
                step_prefix = f"{specialist_id}_" if is_task_force else ""

                pack_payload = await _execute_pack_loop(
                    pack=pack,
                    messages=messages,
                    model_cfg=model_cfg,
                    chat_client=chat_client,
                    run_repository=run_repository,
                    run_id=run_id,
                    step_prefix=step_prefix,
                    max_steps=max_steps,
                    tracer=tracer,
                    specialist_id=specialist_id,
                    event_queue=event_queue,
                )

                prev_finish_payload = pack_payload
                final_payload = pack_payload

    logger.info(
        "Task completed: run_id=%s specialists=%s is_task_force=%s mode=%s",
        run_id.value, specialist_ids, is_task_force, task_force_mode,
    )

    # Write a "run_complete" event — makes run status detection trivial (P8-3).
    _run_complete_ev = {
        "run_id": run_id.value,
        "specialist_ids": specialist_ids,
        "task_force_mode": task_force_mode,
    }
    run_repository.append_event(run_id, "run_complete", _run_complete_ev, step=None)
    _emit(event_queue, "run_complete", _run_complete_ev)

    result = RunResult(
        run_id=run_id,
        run_dir=run_dir,
        workspace_path=workspace_path,
        specialist_id=specialist_ids[0],   # primary specialist (config order)
        model_name=model_cfg.model,
        payload=final_payload,
        required_capabilities=required_capabilities,
        specialist_ids=specialist_ids,
    )

    # Append to the cross-run index so past runs are searchable.
    # Failure is non-fatal — log a warning and return the result regardless.
    try:
        from agent_fabric.infrastructure.workspace.run_index import (
            RunIndexEntry,
            append_to_index,
            embed_text,
        )
        import time
        workspace_root = str(_run_dir_to_workspace_root(run_dir))
        summary_text = (
            final_payload.get("summary")
            or final_payload.get("executive_summary")
            or ""
        )
        entry = RunIndexEntry(
            run_id=run_id.value,
            timestamp=time.time(),
            specialist_ids=specialist_ids,
            prompt_prefix=task.prompt[:200],
            summary=summary_text,
            workspace_path=workspace_path,
            run_dir=run_dir,
            routing_method=routing_method,
            model_name=model_cfg.model,
        )

        # P7-1: Optionally embed the entry for semantic search.
        # When embedding_model is configured the prompt+summary are embedded
        # and stored alongside the index entry.  Embedding failure is non-fatal.
        run_index_cfg = config.run_index
        if run_index_cfg.embedding_model:
            embed_base = (
                run_index_cfg.embedding_base_url or model_cfg.base_url
            )
            try:
                embed_input = f"{task.prompt[:200]} {summary_text}".strip()
                entry.embedding = await embed_text(
                    embed_input,
                    run_index_cfg.embedding_model,
                    embed_base,
                )
                logger.debug(
                    "RunIndex: embedded entry for run %s (model=%s dims=%d)",
                    run_id.value, run_index_cfg.embedding_model, len(entry.embedding),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "RunIndex: embedding failed for run %s (%s); index entry written without embedding",
                    run_id.value, exc,
                )

        append_to_index(workspace_root, entry)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to append to run index: %s", exc)

    # Signal streaming clients that the run is finished.
    _emit(event_queue, "_run_done_", {"run_id": result.run_id.value, "ok": True})

    return result


def _run_dir_to_workspace_root(run_dir: str) -> str:
    """Derive workspace_root from run_dir (``{root}/runs/{run_id}`` → ``{root}``)."""
    from pathlib import Path
    return str(Path(run_dir).parent.parent)


# ---------------------------------------------------------------------------
# Parallel task force helpers
# ---------------------------------------------------------------------------

async def _run_task_force_parallel(
    *,
    specialist_ids: List[str],
    task: Any,  # Task domain object
    workspace_path: str,
    model_cfg: ModelConfig,
    chat_client: ChatClient,
    run_repository: RunRepository,
    run_id: RunId,
    max_steps: int,
    tracer: Any,
    event_queue: Optional[asyncio.Queue],
    specialist_registry: Any,  # SpecialistRegistry protocol
) -> Dict[str, Any]:
    """Run all specialist packs concurrently and merge their payloads.

    Each pack receives the original task prompt with no inter-pack context
    forwarding. Pack errors are captured and included in the merged result
    so one failing pack does not abort the whole task force.
    """
    async def _run_one(specialist_id: str, pack_idx: int) -> Dict[str, Any]:
        pack = specialist_registry.get_pack(specialist_id, workspace_path, task.network_allowed)
        pack_start_ev = {"specialist_id": specialist_id, "pack_index": pack_idx}
        run_repository.append_event(run_id, "pack_start", pack_start_ev, step=None)
        _emit(event_queue, "pack_start", pack_start_ev)
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": pack.system_prompt},
            {"role": "user", "content": f"Task:\n{task.prompt}"},
        ]
        step_prefix = f"{specialist_id}_"
        return await _execute_pack_loop(
            pack=pack,
            messages=messages,
            model_cfg=model_cfg,
            chat_client=chat_client,
            run_repository=run_repository,
            run_id=run_id,
            step_prefix=step_prefix,
            max_steps=max_steps,
            tracer=tracer,
            specialist_id=specialist_id,
            event_queue=event_queue,
        )

    results = await asyncio.gather(
        *[_run_one(sid, idx) for idx, sid in enumerate(specialist_ids)],
        return_exceptions=True,
    )
    return _merge_parallel_payloads(list(results), specialist_ids)


def _merge_parallel_payloads(
    payloads: List[Any],
    specialist_ids: List[str],
) -> Dict[str, Any]:
    """Merge parallel pack payloads into a single combined result dict.

    Returns a dict with:
    - ``pack_results``: mapping from specialist_id → individual payload (or error dict)
    - ``summary``: concatenated per-pack summaries joined with `` | ``
    - ``action``, ``artifacts``, ``next_steps``: standard finish_task fields
    """
    pack_results: Dict[str, Any] = {}
    summaries: List[str] = []

    for sid, payload in zip(specialist_ids, payloads):
        if isinstance(payload, BaseException):
            pack_results[sid] = {
                "error": str(payload),
                "error_type": type(payload).__name__,
            }
            summaries.append(f"{sid}: error — {payload}")
        else:
            pack_results[sid] = payload
            pack_summary = payload.get("summary") or payload.get("executive_summary") or ""
            if pack_summary:
                summaries.append(f"{sid}: {pack_summary}")

    combined_summary = " | ".join(summaries) if summaries else "Parallel task force completed."
    return {
        "action": "final",
        "pack_results": pack_results,
        "summary": combined_summary,
        "artifacts": [],
        "next_steps": [],
    }


# ---------------------------------------------------------------------------
# Pack tool loop
# ---------------------------------------------------------------------------

async def _execute_pack_loop(
    *,
    pack: Any,  # SpecialistPack protocol
    messages: List[Dict[str, Any]],
    model_cfg: ModelConfig,
    chat_client: ChatClient,
    run_repository: RunRepository,
    run_id: RunId,
    step_prefix: str = "",
    max_steps: int = 40,
    tracer: Any = None,
    specialist_id: str = "",
    event_queue: Optional[asyncio.Queue] = None,
) -> Dict[str, Any]:
    """Run one specialist pack's tool loop until ``finish_task`` or ``max_steps``.

    ``messages`` is mutated in place as the conversation accumulates.
    ``pack.aopen()`` is called before the loop; ``pack.aclose()`` in a
    ``finally`` block — ensuring MCP subprocess cleanup even on error.

    Returns the final payload dict (always has ``action: "final"``).
    """
    from agent_fabric.infrastructure.telemetry import _NOOP_TRACER
    if tracer is None:
        tracer = _NOOP_TRACER

    payload: Dict[str, Any] = {}
    # Tracks whether any non-finish tool has been attempted in this pack loop.
    # finish_task is rejected until this is True so the LLM cannot claim
    # completion without having done any actual work.
    any_non_finish_tool_called = False

    # aopen() is INSIDE the try block so that aclose() runs even if aopen()
    # fails partway (e.g. MCPAugmentedPack partially connects before one
    # session raises — the finally block safely no-ops already-closed sessions).
    try:
        await pack.aopen()
        for step in range(max_steps):
            step_key = f"{step_prefix}step_{step}"
            logger.debug("Step %s: %d messages in context", step_key, len(messages))
            _llm_req_ev = {"step": step, "message_count": len(messages)}
            run_repository.append_event(run_id, "llm_request", _llm_req_ev, step=step_key)
            _emit(event_queue, "llm_request", _llm_req_ev, step=step_key)

            with tracer.start_as_current_span("fabric.llm_call") as llm_span:
                llm_span.set_attribute("step", step)
                llm_span.set_attribute("specialist_id", specialist_id)
                llm_span.set_attribute("model", model_cfg.model)
                llm_span.set_attribute("message_count", len(messages))
                response = await chat_client.chat(
                    messages=messages,
                    model=model_cfg.model,
                    tools=pack.tool_definitions,
                    temperature=model_cfg.temperature,
                    top_p=model_cfg.top_p,
                    max_tokens=model_cfg.max_tokens,
                )
                llm_span.set_attribute("tool_calls_returned", len(response.tool_calls))

            # Drain pending cloud_fallback events from FallbackChatClient (if used).
            # FallbackChatClient.pop_events() returns [] for plain ChatClient instances.
            if hasattr(chat_client, "pop_events"):
                for fb_event in chat_client.pop_events():
                    run_repository.append_event(
                        run_id, "cloud_fallback", fb_event, step=step_key,
                    )
                    _emit(event_queue, "cloud_fallback", fb_event, step=step_key)
                    logger.info(
                        "Cloud fallback used: step=%s reason=%s local=%s cloud=%s",
                        step_key, fb_event.get("reason"),
                        fb_event.get("local_model"), fb_event.get("cloud_model"),
                    )

            _llm_resp_ev = {
                "content": (response.content or "")[:MAX_LLM_CONTENT_IN_RUNLOG_CHARS],
                "tool_calls": [
                    {"name": tc.tool_name, "call_id": tc.call_id}
                    for tc in response.tool_calls
                ],
            }
            run_repository.append_event(run_id, "llm_response", _llm_resp_ev, step=step_key)
            _emit(event_queue, "llm_response", _llm_resp_ev, step=step_key)

            if not response.has_tool_calls:
                # LLM responded with plain text (no tool calls) — treat as final.
                # This handles models that don't support function calling and simply
                # respond in prose.
                logger.warning(
                    "Step %s: LLM returned plain text with no tool calls; using as final payload",
                    step_key,
                )
                payload = {
                    "action": "final",
                    "summary": response.content or "",
                    "artifacts": [],
                    "next_steps": [],
                    "notes": "Model did not call finish_task; using text response as summary.",
                }
                break

            # Build the assistant turn with tool_calls for the conversation history.
            messages.append(
                _make_assistant_tool_turn(response.content, response.tool_calls)
            )

            finish_payload: Optional[Dict[str, Any]] = None

            for tc in response.tool_calls:
                _tc_ev = {"tool": tc.tool_name, "args": tc.arguments}
                run_repository.append_event(run_id, "tool_call", _tc_ev, step=step_key)
                _emit(event_queue, "tool_call", _tc_ev, step=step_key)

                if tc.tool_name == pack.finish_tool_name:
                    # Structural quality gate: the LLM must attempt at least one
                    # non-finish tool before finish_task is accepted.  This prevents
                    # lazy completions where the model claims success without doing
                    # any work.  Tool failures count — if all tools fail the LLM can
                    # still call finish_task to report it, as long as it tried.
                    if not any_non_finish_tool_called:
                        logger.warning(
                            "Step %s: finish_task called before any tool was used; "
                            "sending error to LLM for retry",
                            step_key,
                        )
                        error_result = {
                            "error": "finish_task_called_without_doing_work",
                            "message": (
                                "You must use at least one tool to actually complete "
                                "the task before calling finish_task. Call finish_task "
                                "only after you have done the work and verified it."
                            ),
                            "hint": (
                                "Use your available tools first (e.g. shell, write_file, "
                                "web_search), then call finish_task."
                            ),
                        }
                        messages.append(
                            _make_tool_result(tc.call_id, json.dumps(error_result))
                        )
                        _no_work_ev = {"tool": tc.tool_name, "result": error_result}
                        run_repository.append_event(run_id, "tool_result", _no_work_ev, step=step_key)
                        _emit(event_queue, "tool_result", _no_work_ev, step=step_key)
                        continue  # Do NOT set finish_payload; LLM must do work first.

                    # Validate required fields before accepting as the final payload.
                    # If any are missing, send the error back to the LLM as a tool
                    # result so it can retry with complete arguments.
                    missing = [
                        f for f in pack.finish_required_fields if f not in tc.arguments
                    ]
                    if missing:
                        logger.warning(
                            "Step %s: finish_task missing required fields %s; sending error to LLM for retry",
                            step_key, missing,
                        )
                        error_result = {
                            "error": "finish_task called with missing required fields",
                            "missing_fields": missing,
                            "required_fields": pack.finish_required_fields,
                            "hint": "Call finish_task again with all required fields populated.",
                        }
                        messages.append(
                            _make_tool_result(tc.call_id, json.dumps(error_result))
                        )
                        _missing_fields_ev = {"tool": tc.tool_name, "result": error_result}
                        run_repository.append_event(run_id, "tool_result", _missing_fields_ev, step=step_key)
                        _emit(event_queue, "tool_result", _missing_fields_ev, step=step_key)
                        continue  # Do NOT set finish_payload; LLM must retry.

                    finish_payload = {"action": "final", **tc.arguments}
                    messages.append(_make_tool_result(tc.call_id, _FINISH_TOOL_RESULT_CONTENT))
                    _finish_ev = {"tool": tc.tool_name, "result": {"status": "task_completed"}}
                    run_repository.append_event(run_id, "tool_result", _finish_ev, step=step_key)
                    _emit(event_queue, "tool_result", _finish_ev, step=step_key)
                    continue

                # Mark that the LLM has attempted at least one non-finish tool.
                # Set before execution so that tool failures still count.
                any_non_finish_tool_called = True
                error_type: Optional[str] = None
                error_message: str = ""
                with tracer.start_as_current_span("fabric.tool_call") as tool_span:
                    tool_span.set_attribute("tool_name", tc.tool_name)
                    tool_span.set_attribute("specialist_id", specialist_id)
                    try:
                        result = await pack.execute_tool(tc.tool_name, tc.arguments)
                    except PermissionError as exc:
                        # Sandbox violation: path escape or disallowed command.
                        result = {"error": "permission_denied", "message": str(exc)}
                        error_type, error_message = "permission", str(exc)
                    except (ValueError, TypeError) as exc:
                        # Bad arguments supplied by the LLM to the tool.
                        result = {"error": "invalid_arguments", "message": str(exc)}
                        error_type, error_message = "invalid_args", str(exc)
                    except OSError as exc:
                        # Filesystem or subprocess I/O error.
                        result = {"error": "io_error", "message": str(exc)}
                        error_type, error_message = "io_error", str(exc)
                    except Exception as exc:  # noqa: BLE001
                        # Unexpected error — catch-all so one bad tool never kills the run.
                        # KeyboardInterrupt / SystemExit are BaseException, not Exception,
                        # so they propagate normally.
                        result = {
                            "error": "unexpected_error",
                            "message": str(exc),
                            "error_type": type(exc).__name__,
                        }
                        error_type, error_message = "unexpected", str(exc)

                if error_type is not None:
                    logger.warning(
                        "Step %s: tool %r error (%s): %s",
                        step_key, tc.tool_name, error_type, error_message,
                    )
                    _terr_ev = {
                        "tool": tc.tool_name,
                        "error_type": error_type,
                        "error_message": error_message,
                    }
                    run_repository.append_event(run_id, "tool_error", _terr_ev, step=step_key)
                    _emit(event_queue, "tool_error", _terr_ev, step=step_key)
                    if error_type == "permission":
                        # Sandbox violation — write a dedicated security_event so the
                        # audit trail is distinct from ordinary tool errors.
                        logger.warning(
                            "Security event: sandbox violation by tool %r: %s",
                            tc.tool_name, error_message,
                        )
                        _sec_ev = {
                            "event_type": "sandbox_violation",
                            "tool": tc.tool_name,
                            "error_message": error_message,
                        }
                        run_repository.append_event(run_id, "security_event", _sec_ev, step=step_key)
                        _emit(event_queue, "security_event", _sec_ev, step=step_key)
                else:
                    _tresult_ev = {"tool": tc.tool_name, "result": result}
                    run_repository.append_event(run_id, "tool_result", _tresult_ev, step=step_key)
                    _emit(event_queue, "tool_result", _tresult_ev, step=step_key)
                messages.append(_make_tool_result(tc.call_id, json.dumps(result, ensure_ascii=False)))

            if finish_payload is not None:
                payload = finish_payload
                logger.info(
                    "Pack loop completed: step=%s pack=%s",
                    step_key, step_prefix.rstrip("_") or "single",
                )
                break

        else:
            # for-else: loop completed without breaking → max_steps reached.
            logger.warning(
                "max_steps (%d) reached without finish_task: run_id=%s step_prefix=%r",
                max_steps, run_id.value, step_prefix,
            )
            payload = {
                "action": "final",
                "summary": f"Reached max_steps ({max_steps}) without completion.",
                "artifacts": [],
                "next_steps": ["Increase max_steps or refine task."],
                "notes": "See runlog for details.",
            }
    finally:
        await pack.aclose()

    return payload


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_assistant_tool_turn(
    content: Optional[str],
    tool_calls: list,
) -> Dict[str, Any]:
    """Build the ``assistant`` message dict for a turn that contains tool calls."""
    return {
        "role": "assistant",
        "content": content,
        "tool_calls": [
            {
                "id": tc.call_id,
                "type": "function",
                "function": {
                    "name": tc.tool_name,
                    "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                },
            }
            for tc in tool_calls
        ],
    }


def _make_tool_result(call_id: str, content: str) -> Dict[str, Any]:
    """Build the ``tool`` message dict for a tool call result."""
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": content,
    }
