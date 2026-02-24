"""Execute task use case.

Flow: recruit specialist → create run → tool loop until finish_task or max_steps.

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
from agent_fabric.application.recruit import recruit_specialist

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

    1. Recruit a specialist (keyword-based if not set on ``task``).
    2. Create a run directory + workspace.
    3. Run a tool loop until the specialist calls ``finish_task`` or ``max_steps``
       is reached.
    4. Return a ``RunResult`` with the run id, paths, and final payload.

    Args:
        task: Prompt, optional specialist override, model key, and network flag.
        chat_client: LLM interface (``ChatClient`` port).
        run_repository: Creates run dirs and appends log events (``RunRepository`` port).
        specialist_registry: Resolves pack by id (``SpecialistRegistry`` port).
        config: Fabric configuration (models, specialists, flags).
        resolved_model_cfg: Pre-resolved model config (e.g. from ``resolve_llm``).
            Falls back to ``config.models[task.model_key]`` when not provided.
        max_steps: Maximum LLM turns before aborting.

    Returns:
        ``RunResult`` with payload set to the arguments of the ``finish_task`` call
        (plus ``action: "final"``), or a timeout payload if ``max_steps`` is reached.

    Raises:
        RecruitError: When the specialist id is not found in config.
    """
    # --- recruit -----------------------------------------------------------------
    specialist_id = task.specialist_id or recruit_specialist(task.prompt, config)
    if specialist_id not in config.specialists:
        raise RecruitError(f"Unknown specialist: {specialist_id!r}")

    # --- setup -------------------------------------------------------------------
    run_id, run_dir, workspace_path = run_repository.create_run()
    logger.info("Task started: specialist=%s run_id=%s", specialist_id, run_id.value)
    pack = specialist_registry.get_pack(specialist_id, workspace_path, task.network_allowed)
    model_cfg = resolved_model_cfg or config.models.get(task.model_key) or config.models["quality"]

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": pack.system_prompt},
        {"role": "user", "content": f"Task:\n{task.prompt}"},
    ]

    payload: Dict[str, Any] = {}

    # --- tool loop ---------------------------------------------------------------
    for step in range(max_steps):
        logger.debug("Step %d/%d: %d messages in context", step, max_steps, len(messages))
        run_repository.append_event(
            run_id,
            "llm_request",
            {"step": step, "message_count": len(messages)},
            step=f"step_{step}",
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
            step=f"step_{step}",
        )

        if not response.has_tool_calls:
            # LLM responded with plain text (no tool calls) — treat as final.
            # This handles models that don't support function calling and simply
            # respond in prose.
            logger.warning(
                "Step %d: LLM returned plain text with no tool calls; using as final payload",
                step,
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
                step=f"step_{step}",
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
                        "Step %d: finish_task missing required fields %s; sending error to LLM for retry",
                        step, missing,
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
                        step=f"step_{step}",
                    )
                    continue  # Do NOT set finish_payload; LLM must retry.

                finish_payload = {"action": "final", **tc.arguments}
                messages.append(_make_tool_result(tc.call_id, _FINISH_TOOL_RESULT_CONTENT))
                run_repository.append_event(
                    run_id,
                    "tool_result",
                    {"tool": tc.tool_name, "result": {"status": "task_completed"}},
                    step=f"step_{step}",
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
                    "Step %d: tool %r error (%s): %s",
                    step, tc.tool_name, error_type, error_message,
                )
                run_repository.append_event(
                    run_id,
                    "tool_error",
                    {
                        "tool": tc.tool_name,
                        "error_type": error_type,
                        "error_message": error_message,
                    },
                    step=f"step_{step}",
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
                        step=f"step_{step}",
                    )
            else:
                run_repository.append_event(
                    run_id,
                    "tool_result",
                    {"tool": tc.tool_name, "result": result},
                    step=f"step_{step}",
                )
            messages.append(_make_tool_result(tc.call_id, json.dumps(result, ensure_ascii=False)))

        if finish_payload is not None:
            payload = finish_payload
            logger.info(
                "Task completed: run_id=%s specialist=%s steps=%d",
                run_id.value, specialist_id, step + 1,
            )
            break

    else:
        # for-else: loop completed without breaking → max_steps reached.
        logger.warning(
            "max_steps (%d) reached without finish_task: run_id=%s specialist=%s",
            max_steps, run_id.value, specialist_id,
        )
        payload = {
            "action": "final",
            "summary": f"Reached max_steps ({max_steps}) without completion.",
            "artifacts": [],
            "next_steps": ["Increase max_steps or refine task."],
            "notes": "See runlog for details.",
        }

    return RunResult(
        run_id=run_id,
        run_dir=run_dir,
        workspace_path=workspace_path,
        specialist_id=specialist_id,
        model_name=model_cfg.model,
        payload=payload,
    )


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
