"""Execute task use case.

Flow: recruit specialist(s) → create run → for each specialist, run a tool
loop until finish_task or max_steps; context from earlier packs is forwarded
to later packs so the task force shares progress.

Dependencies are injected (ports only); this module never imports from
``infrastructure`` or ``interfaces``.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from agent_fabric.config import FabricConfig, ModelConfig
from agent_fabric.config.constants import MAX_LLM_CONTENT_IN_RUNLOG_CHARS
from agent_fabric.domain import RecruitError, RunId, RunResult, Task
from agent_fabric.application.ports import ChatClient, RunRepository, SpecialistRegistry
from agent_fabric.application.recruit import recruit_specialist, RecruitmentResult

logger = logging.getLogger(__name__)


_FINISH_TOOL_RESULT_CONTENT = json.dumps({"ok": True, "status": "task_completed"})


async def execute_task(
    task: Task,
    *,
    chat_client: ChatClient,
    run_repository: RunRepository,
    specialist_registry: SpecialistRegistry,
    config: FabricConfig,
    resolved_model_cfg: Optional[ModelConfig] = None,
    max_steps: int = 40,
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

    Returns:
        ``RunResult`` with payload set to the arguments of the final pack's
        ``finish_task`` call (plus ``action: "final"``), or a timeout payload
        if ``max_steps`` is reached for the last specialist.

    Raises:
        RecruitError: When a specialist id is not found in config.
    """
    # --- recruit -----------------------------------------------------------------
    if task.specialist_id:
        specialist_ids: List[str] = [task.specialist_id]
        required_capabilities: List[str] = []
        routing_method = "explicit"
    else:
        recruitment: RecruitmentResult = recruit_specialist(task.prompt, config)
        specialist_ids = recruitment.specialist_ids
        required_capabilities = recruitment.required_capabilities
        routing_method = "capability_routing"

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
    run_repository.append_event(
        run_id,
        "recruitment",
        {
            "specialist_id": specialist_ids[0],   # Phase 2 compat: primary specialist
            "specialist_ids": specialist_ids,       # Phase 3: full task force list
            "required_capabilities": required_capabilities,
            "routing_method": routing_method,
            "is_task_force": is_task_force,
        },
        step=None,
    )

    model_cfg = resolved_model_cfg or config.models.get(task.model_key) or config.models["quality"]

    # --- pack loop ---------------------------------------------------------------
    # Each specialist gets a fresh message context.  Subsequent specialists receive
    # the previous pack's finish payload as additional context so they can build on
    # what was already done.
    prev_finish_payload: Optional[Dict[str, Any]] = None
    final_payload: Dict[str, Any] = {}

    for pack_idx, specialist_id in enumerate(specialist_ids):
        pack = specialist_registry.get_pack(specialist_id, workspace_path, task.network_allowed)

        if is_task_force:
            run_repository.append_event(
                run_id,
                "pack_start",
                {"specialist_id": specialist_id, "pack_index": pack_idx},
                step=None,
            )
            logger.info(
                "Task force: starting pack %d/%d specialist=%s run_id=%s",
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
        )

        prev_finish_payload = pack_payload
        final_payload = pack_payload

    logger.info(
        "Task completed: run_id=%s specialists=%s is_task_force=%s",
        run_id.value, specialist_ids, is_task_force,
    )

    return RunResult(
        run_id=run_id,
        run_dir=run_dir,
        workspace_path=workspace_path,
        specialist_id=specialist_ids[0],   # primary specialist (config order)
        model_name=model_cfg.model,
        payload=final_payload,
        required_capabilities=required_capabilities,
        specialist_ids=specialist_ids,
    )


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
) -> Dict[str, Any]:
    """Run one specialist pack's tool loop until ``finish_task`` or ``max_steps``.

    ``messages`` is mutated in place as the conversation accumulates.

    Returns the final payload dict (always has ``action: "final"``).
    """
    payload: Dict[str, Any] = {}

    for step in range(max_steps):
        step_key = f"{step_prefix}step_{step}"
        logger.debug("Step %s: %d messages in context", step_key, len(messages))
        run_repository.append_event(
            run_id,
            "llm_request",
            {"step": step, "message_count": len(messages)},
            step=step_key,
        )

        response = await chat_client.chat(
            messages=messages,
            model=model_cfg.model,
            tools=pack.tool_definitions,
            temperature=model_cfg.temperature,
            top_p=model_cfg.top_p,
            max_tokens=model_cfg.max_tokens,
        )

        run_repository.append_event(
            run_id,
            "llm_response",
            {
                "content": (response.content or "")[:MAX_LLM_CONTENT_IN_RUNLOG_CHARS],
                "tool_calls": [
                    {"name": tc.tool_name, "call_id": tc.call_id}
                    for tc in response.tool_calls
                ],
            },
            step=step_key,
        )

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
            run_repository.append_event(
                run_id,
                "tool_call",
                {"tool": tc.tool_name, "args": tc.arguments},
                step=step_key,
            )

            if tc.tool_name == pack.finish_tool_name:
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
                    run_repository.append_event(
                        run_id,
                        "tool_result",
                        {"tool": tc.tool_name, "result": error_result},
                        step=step_key,
                    )
                    continue  # Do NOT set finish_payload; LLM must retry.

                finish_payload = {"action": "final", **tc.arguments}
                messages.append(_make_tool_result(tc.call_id, _FINISH_TOOL_RESULT_CONTENT))
                run_repository.append_event(
                    run_id,
                    "tool_result",
                    {"tool": tc.tool_name, "result": {"status": "task_completed"}},
                    step=step_key,
                )
                continue

            error_type: Optional[str] = None
            error_message: str = ""
            try:
                result = pack.execute_tool(tc.tool_name, tc.arguments)
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
                run_repository.append_event(
                    run_id,
                    "tool_error",
                    {
                        "tool": tc.tool_name,
                        "error_type": error_type,
                        "error_message": error_message,
                    },
                    step=step_key,
                )
                if error_type == "permission":
                    # Sandbox violation — write a dedicated security_event so the
                    # audit trail is distinct from ordinary tool errors.
                    logger.warning(
                        "Security event: sandbox violation by tool %r: %s",
                        tc.tool_name, error_message,
                    )
                    run_repository.append_event(
                        run_id,
                        "security_event",
                        {
                            "event_type": "sandbox_violation",
                            "tool": tc.tool_name,
                            "error_message": error_message,
                        },
                        step=step_key,
                    )
            else:
                run_repository.append_event(
                    run_id,
                    "tool_result",
                    {"tool": tc.tool_name, "result": result},
                    step=step_key,
                )
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
