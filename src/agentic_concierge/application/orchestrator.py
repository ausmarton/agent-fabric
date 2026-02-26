"""LLM Orchestrator: decomposes tasks, assigns specialists, plans execution.

Phase 12-5 to 12-9: replaces the naive ``llm_recruit_specialist`` call with a
richer orchestration step that produces per-specialist briefs, selects the
execution mode (sequential vs parallel), and flags whether synthesis is
required after all specialists complete.

Falls back to ``llm_recruit_specialist`` on any error — zero regression.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from agentic_concierge.config import ConciergeConfig

if TYPE_CHECKING:
    from agentic_concierge.application.ports import ChatClient

logger = logging.getLogger(__name__)


@dataclass
class SpecialistBrief:
    """A targeted sub-task description for a specific specialist."""

    specialist_id: str
    brief: str  # targeted instructions / sub-task for this specialist


@dataclass
class OrchestrationPlan:
    """The orchestrator's task decomposition and assignment plan.

    ``specialist_assignments`` is an ordered list of (specialist_id, brief) pairs.
    ``mode`` is ``"sequential"`` or ``"parallel"``.
    ``synthesis_required`` is True when a synthesis step is needed after execution.
    ``routing_method`` is ``"orchestrator"`` on success or the fallback's method.
    ``required_capabilities`` is derived from the assigned specialists' capabilities
    for RunResult / runlog compatibility with the existing RecruitmentResult shape.
    """

    specialist_assignments: List[SpecialistBrief]
    mode: str  # "sequential" | "parallel"
    synthesis_required: bool
    reasoning: str
    routing_method: str  # "orchestrator" | fallback routing_method values
    required_capabilities: List[str] = field(default_factory=list)


def _build_orchestrator_tool_def() -> Dict[str, Any]:
    """Build the create_plan tool definition."""
    return {
        "type": "function",
        "function": {
            "name": "create_plan",
            "description": (
                "Create a task execution plan by assigning sub-tasks to specialists. "
                "Call this tool exactly once with the complete plan."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "assignments": {
                        "type": "array",
                        "description": "Ordered list of specialist assignments.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "specialist_id": {
                                    "type": "string",
                                    "description": "Specialist ID (e.g. 'engineering', 'research').",
                                },
                                "brief": {
                                    "type": "string",
                                    "description": "Specific sub-task instructions for this specialist.",
                                },
                            },
                            "required": ["specialist_id", "brief"],
                        },
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["sequential", "parallel"],
                        "description": (
                            "'sequential' when specialists depend on each other's outputs; "
                            "'parallel' when tasks are independent."
                        ),
                    },
                    "synthesis_required": {
                        "type": "boolean",
                        "description": "True when a final synthesis step is needed to combine outputs.",
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "One sentence explaining the orchestration decision.",
                    },
                },
                "required": ["assignments", "mode", "synthesis_required", "reasoning"],
            },
        },
    }


def _build_orchestrator_messages(prompt: str, config: ConciergeConfig) -> List[Dict[str, Any]]:
    """Build the system + user messages for the orchestrator LLM call."""
    specialist_lines = "\n".join(
        f"- {name} ({', '.join(spec.capabilities or [])}): {spec.description}"
        for name, spec in config.specialists.items()
    )
    system = (
        "You are a task orchestrator. Decompose the given task into clear sub-task assignments "
        "for the available specialist agents.\n\n"
        f"Available specialists:\n{specialist_lines}\n\n"
        "Guidelines:\n"
        "- Assign each specialist a specific, actionable brief.\n"
        "- Use 'sequential' mode when later specialists need earlier specialists' outputs.\n"
        "- Use 'parallel' mode when tasks are independent and can run concurrently.\n"
        "- Set synthesis_required=true when multiple specialists produce outputs that need combining.\n"
        "- For single-specialist tasks, assign only that specialist.\n"
        "Call create_plan with the complete assignment plan."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Task: {prompt}"},
    ]


def _derive_required_capabilities(
    specialist_ids: List[str], config: ConciergeConfig
) -> List[str]:
    """Derive required capabilities from the assigned specialists' declared capabilities."""
    caps: List[str] = []
    for sid in specialist_ids:
        spec_cfg = config.specialists.get(sid)
        if spec_cfg:
            for cap in spec_cfg.capabilities:
                if cap not in caps:
                    caps.append(cap)
    return caps


async def orchestrate_task(
    prompt: str,
    config: ConciergeConfig,
    *,
    chat_client: "ChatClient",
    model: str,
) -> OrchestrationPlan:
    """Decompose a task, assign specialists, and plan execution mode.

    Makes one LLM call with the ``create_plan`` tool.  Falls back to
    ``llm_recruit_specialist`` on any error or when the LLM returns no
    usable tool call — zero regression with Phase 5 routing.

    Args:
        prompt: The task prompt to decompose.
        config: Concierge config (specialists, models).
        chat_client: LLM interface.
        model: Model name to use for the orchestrator call.

    Returns:
        ``OrchestrationPlan`` with routing_method ``"orchestrator"`` on success,
        or a plan built from the fallback ``llm_recruit_specialist`` result.
    """
    from agentic_concierge.infrastructure.telemetry import get_tracer

    tracer = get_tracer()

    try:
        messages = _build_orchestrator_messages(prompt, config)
        tool_def = _build_orchestrator_tool_def()
        with tracer.start_as_current_span("concierge.orchestrator_call") as span:
            span.set_attribute("model", model)
            response = await chat_client.chat(
                messages,
                model,
                tools=[tool_def],
                temperature=0.0,
                max_tokens=512,
            )
            span.set_attribute("tool_call_returned", bool(response.tool_calls))
    except Exception as exc:
        logger.warning("Orchestrator LLM call failed (%s); falling back to llm_recruit_specialist", exc)
        return await _fallback_plan(prompt, config, chat_client=chat_client, model=model)

    # Parse the create_plan tool call
    if not response.tool_calls:
        logger.info("Orchestrator returned no tool call; falling back to llm_recruit_specialist")
        return await _fallback_plan(prompt, config, chat_client=chat_client, model=model)

    tc = response.tool_calls[0]
    if tc.tool_name != "create_plan":
        logger.info("Orchestrator called unexpected tool %r; falling back", tc.tool_name)
        return await _fallback_plan(prompt, config, chat_client=chat_client, model=model)

    raw_assignments = tc.arguments.get("assignments", [])
    mode = tc.arguments.get("mode", "sequential")
    synthesis_required = tc.arguments.get("synthesis_required", False)
    reasoning = tc.arguments.get("reasoning", "")

    # Filter to known specialist IDs only
    known_ids = set(config.specialists.keys())
    assignments: List[SpecialistBrief] = []
    for a in raw_assignments:
        sid = a.get("specialist_id", "")
        brief = a.get("brief", "")
        if sid in known_ids:
            assignments.append(SpecialistBrief(specialist_id=sid, brief=brief))
        else:
            logger.warning("Orchestrator assigned unknown specialist %r; skipping", sid)

    if not assignments:
        logger.info("Orchestrator produced no valid assignments; falling back")
        return await _fallback_plan(prompt, config, chat_client=chat_client, model=model)

    specialist_ids = [a.specialist_id for a in assignments]
    required_capabilities = _derive_required_capabilities(specialist_ids, config)

    # Force synthesis when multiple specialists assigned
    if len(assignments) > 1:
        synthesis_required = True

    logger.info(
        "Orchestrator plan: specialists=%s mode=%s synthesis=%s reasoning=%r",
        specialist_ids, mode, synthesis_required, reasoning,
    )
    return OrchestrationPlan(
        specialist_assignments=assignments,
        mode=mode,
        synthesis_required=synthesis_required,
        reasoning=reasoning,
        routing_method="orchestrator",
        required_capabilities=required_capabilities,
    )


async def _fallback_plan(
    prompt: str,
    config: ConciergeConfig,
    *,
    chat_client: "ChatClient",
    model: str,
) -> OrchestrationPlan:
    """Fall back to llm_recruit_specialist and wrap the result as an OrchestrationPlan."""
    from agentic_concierge.application.recruit import llm_recruit_specialist

    recruitment = await llm_recruit_specialist(
        prompt, config, chat_client=chat_client, model=model
    )
    assignments = [
        SpecialistBrief(specialist_id=sid, brief="")
        for sid in recruitment.specialist_ids
    ]
    return OrchestrationPlan(
        specialist_assignments=assignments,
        mode="sequential",
        synthesis_required=len(recruitment.specialist_ids) > 1,
        reasoning="",
        routing_method=recruitment.routing_method,
        required_capabilities=recruitment.required_capabilities,
    )
