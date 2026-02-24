"""Recruit specialist(s) for a task.

Phase 2: capability-based two-stage routing returning a single specialist.
Phase 3: greedy multi-pack selection — when required capabilities span
multiple specialists, a *task force* of two or more packs is recruited.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List

from agent_fabric.config import FabricConfig

logger = logging.getLogger(__name__)


@dataclass
class RecruitmentResult:
    """Outcome of routing a task to a specialist or task force.

    ``specialist_ids`` is the ordered list of specialist packs to recruit.
    For single-pack runs this has exactly one element; for multi-pack task
    forces it has two or more (in execution order, sorted by config position).

    ``required_capabilities`` is the list of capability IDs inferred from the
    task prompt (empty when routing fell back to keyword scoring).

    ``specialist_id`` (property) returns the primary/first specialist for
    backward-compatible code that only needs one pack name.
    ``is_task_force`` (property) is True when more than one pack is recruited.
    """
    specialist_ids: List[str]
    required_capabilities: List[str] = field(default_factory=list)

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


def recruit_specialist(prompt: str, cfg: FabricConfig) -> RecruitmentResult:
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
    from agent_fabric.config.capabilities import CAPABILITY_KEYWORDS

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
            )
        logger.debug("Recruited specialist: research (default fallback, no keywords matched)")
        return RecruitmentResult(
            specialist_ids=["research"],
            required_capabilities=required_caps,
        )

    logger.debug(
        "Recruited specialist: %s (keyword score=%d)", best_name, best_score,
    )
    return RecruitmentResult(
        specialist_ids=[best_name],
        required_capabilities=required_caps,
    )
