"""Recruit specialist(s) for a task.

Phase 2: capability-based two-stage routing returning a single specialist.
Phase 3: greedy multi-pack selection — when required capabilities span
multiple specialists, a *task force* of two or more packs is recruited.
Phase 5: LLM-driven routing — an LLM planning call infers required capabilities
from the task prompt; keyword routing is the fallback.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List

from agentic_concierge.config import ConciergeConfig

if TYPE_CHECKING:
    from agentic_concierge.application.ports import ChatClient

logger = logging.getLogger(__name__)


@dataclass
class RecruitmentResult:
    """Outcome of routing a task to a specialist or task force.

    ``specialist_ids`` is the ordered list of specialist packs to recruit.
    For single-pack runs this has exactly one element; for multi-pack task
    forces it has two or more (in execution order, sorted by config position).

    ``required_capabilities`` is the list of capability IDs inferred from the
    task prompt (empty when routing fell back to keyword scoring).

    ``routing_method`` records how the specialist(s) were selected:
    - ``"llm_routing"``   — LLM planning call succeeded and produced capabilities.
    - ``"keyword_routing"`` — capability keyword matching (Stage 1+2 algorithm).
    - ``"keyword_fallback"`` — keyword scoring or hardcoded heuristic fallback.

    ``specialist_id`` (property) returns the primary/first specialist for
    backward-compatible code that only needs one pack name.
    ``is_task_force`` (property) is True when more than one pack is recruited.
    """
    specialist_ids: List[str]
    required_capabilities: List[str] = field(default_factory=list)
    routing_method: str = "keyword_routing"

    @property
    def specialist_id(self) -> str:
        """Primary specialist (first in execution order). Backward-compatible accessor."""
        return self.specialist_ids[0]

    @property
    def is_task_force(self) -> bool:
        """True when more than one specialist is recruited for this task."""
        return len(self.specialist_ids) > 1


def infer_capabilities(
    prompt: str,
    capability_keywords: Dict[str, List[str]],
) -> List[str]:
    """Determine which capability IDs are required by the prompt.

    A capability is required when at least one of its keywords appears
    (case-insensitively) as a substring of the prompt.  Multi-word keywords
    such as ``"systematic review"`` match as phrases.

    Returns capability IDs in the iteration order of ``capability_keywords``
    (definition order).
    """
    p = prompt.lower()
    return [cap for cap, kws in capability_keywords.items() if any(kw in p for kw in kws)]


def _greedy_select_specialists(
    required_caps: List[str],
    specialists: Dict[str, Any],
    name_order: Dict[str, int],
) -> List[str]:
    """Greedily select a minimum set of specialists to cover all required capabilities.

    Algorithm:
    1. Start with the full set of uncovered required capabilities.
    2. Repeatedly pick the specialist that covers the most uncovered capabilities
       (ties broken by config insertion order).
    3. Remove the newly covered capabilities from the uncovered set.
    4. Stop when all capabilities are covered or no more candidates can help.

    Returns specialist IDs sorted by config insertion order so execution order
    is deterministic and config-driven (not dependent on greedy selection order).

    If no specialist can cover any required capability, returns an empty list
    (callers fall back to keyword scoring).
    """
    uncovered = set(required_caps)
    selected: List[str] = []
    candidates: Dict[str, Any] = dict(specialists)  # shallow copy; pop as selected

    while uncovered and candidates:
        # Candidate that covers the most uncovered capabilities.
        # Tie: prefer the one with the lowest config-insertion index.
        best_name = min(
            candidates,
            key=lambda n: (
                -sum(1 for c in uncovered if c in candidates[n].capabilities),
                name_order[n],
            ),
        )
        best_coverage = sum(1 for c in uncovered if c in candidates[best_name].capabilities)

        if best_coverage == 0:
            break  # remaining capabilities are not covered by any remaining specialist

        selected.append(best_name)
        uncovered -= set(candidates[best_name].capabilities)
        del candidates[best_name]

    # Return in config order for deterministic execution.
    selected.sort(key=lambda n: name_order[n])
    return selected


def recruit_specialist(prompt: str, cfg: ConciergeConfig) -> RecruitmentResult:
    """Choose specialist(s) for the task using multi-pack capability routing.

    **Stage 1 — capability inference:**
    Keywords from ``CAPABILITY_KEYWORDS`` that appear in the prompt indicate
    which capabilities are required.

    **Stage 2 — greedy specialist selection:**
    Specialists are selected greedily to cover all required capabilities.
    If a single specialist covers all required capabilities, only one is
    recruited.  If required capabilities span multiple specialists, a task
    force of two or more is returned (see ``RecruitmentResult.is_task_force``).

    **Fallback:** When no capabilities are inferred (prompt matches no
    capability keywords), the router falls back to scoring each specialist's
    own ``keywords`` list against the prompt — the Phase-1 approach.  When
    that also yields all-zero scores, a final hardcoded heuristic kicks in
    (code/build words → engineering; otherwise → research).

    **Tie-breaking (all stages):** Highest score wins; equal scores resolve
    to whichever specialist appears first in ``cfg.specialists`` (config
    insertion order), giving operators control via config ordering.
    """
    from agentic_concierge.config.capabilities import CAPABILITY_KEYWORDS

    required_caps = infer_capabilities(prompt, CAPABILITY_KEYWORDS)
    name_order = {name: i for i, name in enumerate(cfg.specialists)}

    if required_caps:
        selected_ids = _greedy_select_specialists(required_caps, cfg.specialists, name_order)
        if selected_ids:
            if len(selected_ids) > 1:
                logger.info(
                    "Recruited task force: %s (covers required=%s)",
                    selected_ids, required_caps,
                )
            else:
                logger.debug(
                    "Recruited specialist: %s (capability coverage, required=%s)",
                    selected_ids[0], required_caps,
                )
            return RecruitmentResult(
                specialist_ids=selected_ids,
                required_capabilities=required_caps,
                routing_method="keyword_routing",
            )
        # No specialist covers any required capability — fall through to keyword scoring.
        logger.debug(
            "No specialist covers required capabilities %s; falling back to keyword scoring",
            required_caps,
        )

    # Fallback: keyword scoring against each specialist's keyword list.
    p = prompt.lower()
    kw_scores: Dict[str, int] = {name: 0 for name in cfg.specialists}
    for name, spec in cfg.specialists.items():
        for kw in spec.keywords:
            if kw in p:
                kw_scores[name] += 1

    best_name = min(kw_scores, key=lambda n: (-kw_scores[n], name_order[n]))
    best_score = kw_scores[best_name]

    if best_score == 0:
        # Final hardcoded heuristic for very generic prompts.
        if any(x in p for x in ["code", "build", "implement", "service", "pipeline", "deploy"]):
            logger.debug("Recruited specialist: engineering (hardcoded keyword fallback)")
            return RecruitmentResult(
                specialist_ids=["engineering"],
                required_capabilities=required_caps,
                routing_method="keyword_fallback",
            )
        logger.debug("Recruited specialist: research (default fallback, no keywords matched)")
        return RecruitmentResult(
            specialist_ids=["research"],
            required_capabilities=required_caps,
            routing_method="keyword_fallback",
        )

    logger.debug(
        "Recruited specialist: %s (keyword score=%d)", best_name, best_score,
    )
    return RecruitmentResult(
        specialist_ids=[best_name],
        required_capabilities=required_caps,
        routing_method="keyword_fallback",
    )


# ---------------------------------------------------------------------------
# LLM-driven routing
# ---------------------------------------------------------------------------

def _build_routing_tool_def() -> Dict[str, Any]:
    """Build the select_capabilities tool definition using the current CAPABILITY_KEYWORDS.

    Called lazily (not at module import) so the enum constraint always reflects
    the live capability IDs even if CAPABILITY_KEYWORDS is patched in tests or
    extended at runtime.
    """
    from agentic_concierge.config.capabilities import CAPABILITY_KEYWORDS

    return {
        "type": "function",
        "function": {
            "name": "select_capabilities",
            "description": (
                "Identify which capabilities are needed to complete the task. "
                "Call this tool exactly once with the complete list."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "capabilities": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(CAPABILITY_KEYWORDS.keys())},
                        "description": "Capability IDs required for the task.",
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "One sentence explaining your selection.",
                    },
                },
                "required": ["capabilities"],
            },
        },
    }


def _build_routing_messages(prompt: str, cfg: ConciergeConfig) -> List[Dict[str, Any]]:
    """Build the system + user messages for the LLM routing call."""
    from agentic_concierge.config.capabilities import CAPABILITY_KEYWORDS

    specialist_lines = "\n".join(
        f"- {name} ({', '.join(spec.capabilities)}): {spec.description}"
        for name, spec in cfg.specialists.items()
    )
    capability_lines = "\n".join(
        f"- {cap_id}: {', '.join(kws[:4])}"   # first 4 keywords as examples
        for cap_id, kws in CAPABILITY_KEYWORDS.items()
    )
    system = (
        "You are a task router. Identify which capabilities are required to complete the task.\n\n"
        f"Available specialists:\n{specialist_lines}\n\n"
        f"Available capability IDs:\n{capability_lines}\n\n"
        "Call select_capabilities with ONLY the capability IDs that are clearly needed. "
        "If a capability is not clearly required, omit it. Prefer fewer capabilities over more."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Task: {prompt}"},
    ]


async def llm_recruit_specialist(
    prompt: str,
    cfg: ConciergeConfig,
    *,
    chat_client: "ChatClient",
    model: str,
) -> RecruitmentResult:
    """Route task to specialist(s) using an LLM planning step.

    Makes one LLM call with the select_capabilities tool. The returned
    capability IDs are fed into the existing greedy selection algorithm.
    Falls back to keyword routing if the LLM call fails, returns no tool
    call, or returns no known capability IDs.
    """
    from agentic_concierge.config.capabilities import CAPABILITY_KEYWORDS
    from agentic_concierge.infrastructure.telemetry import get_tracer

    tracer = get_tracer()

    try:
        messages = _build_routing_messages(prompt, cfg)
        routing_tool_def = _build_routing_tool_def()
        with tracer.start_as_current_span("fabric.routing_call") as span:
            span.set_attribute("model", model)
            response = await chat_client.chat(
                messages,
                model,
                tools=[routing_tool_def],
                temperature=0.0,
                max_tokens=256,
            )
            span.set_attribute("tool_call_returned", bool(response.tool_calls))
    except Exception as exc:
        logger.warning("LLM routing call failed (%s); falling back to keyword routing", exc)
        result = recruit_specialist(prompt, cfg)
        return RecruitmentResult(
            specialist_ids=result.specialist_ids,
            required_capabilities=result.required_capabilities,
            routing_method=result.routing_method,
        )

    # Parse tool call
    llm_caps: List[str] = []
    if response.tool_calls:
        tc = response.tool_calls[0]
        if tc.tool_name == "select_capabilities":
            raw = tc.arguments.get("capabilities", [])
            # Filter to known capability IDs only (defence-in-depth; enum in schema also constrains)
            known = set(CAPABILITY_KEYWORDS.keys())
            llm_caps = [c for c in raw if c in known]
            reasoning = tc.arguments.get("reasoning", "")
            logger.info("LLM routing: caps=%s reasoning=%r", llm_caps, reasoning)

    if not llm_caps:
        logger.info("LLM routing returned no usable capabilities; falling back to keyword routing")
        result = recruit_specialist(prompt, cfg)
        return RecruitmentResult(
            specialist_ids=result.specialist_ids,
            required_capabilities=result.required_capabilities,
            routing_method=result.routing_method,
        )

    name_order = {name: i for i, name in enumerate(cfg.specialists)}
    selected_ids = _greedy_select_specialists(llm_caps, cfg.specialists, name_order)

    if not selected_ids:
        logger.info("Greedy selection produced no specialists; falling back to keyword routing")
        result = recruit_specialist(prompt, cfg)
        return RecruitmentResult(
            specialist_ids=result.specialist_ids,
            required_capabilities=result.required_capabilities,
            routing_method=result.routing_method,
        )

    logger.info("LLM routing recruited: %s (from caps=%s)", selected_ids, llm_caps)
    return RecruitmentResult(
        specialist_ids=selected_ids,
        required_capabilities=llm_caps,
        routing_method="llm_routing",
    )
