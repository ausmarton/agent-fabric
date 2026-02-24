"""Recruit specialist(s) for a task. Today: capability-based, single specialist."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List

from agent_fabric.config import FabricConfig

logger = logging.getLogger(__name__)


@dataclass
class RecruitmentResult:
    """Outcome of routing a task to a specialist.

    ``specialist_id`` is the selected specialist pack.
    ``required_capabilities`` is the list of capability IDs inferred from the
    task prompt (empty when routing fell back to keyword scoring).
    """
    specialist_id: str
    required_capabilities: List[str] = field(default_factory=list)


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


def recruit_specialist(prompt: str, cfg: FabricConfig) -> RecruitmentResult:
    """Choose one specialist for the task using two-stage capability routing.

    **Stage 1 — capability inference:**
    Keywords from ``CAPABILITY_KEYWORDS`` that appear in the prompt indicate
    which capabilities are required.

    **Stage 2 — specialist selection:**
    Each specialist is scored by how many required capabilities it declares.
    The specialist with the highest coverage wins.

    **Fallback:** When no capabilities are inferred (prompt matches no
    capability keywords), the router falls back to scoring each specialist's
    own ``keywords`` list against the prompt — the Phase-1 approach.  When
    that also yields all-zero scores, a final hardcoded heuristic kicks in
    (code/build words → engineering; otherwise → research).

    **Tie-breaking (both stages):** Highest score wins; equal scores resolve
    to whichever specialist appears first in ``cfg.specialists`` (config
    insertion order), giving operators control via config ordering.
    """
    from agent_fabric.config.capabilities import CAPABILITY_KEYWORDS

    required_caps = infer_capabilities(prompt, CAPABILITY_KEYWORDS)
    name_order = {name: i for i, name in enumerate(cfg.specialists)}

    if required_caps:
        # Score each specialist by how many required capabilities it covers.
        cap_scores = {
            name: sum(1 for c in required_caps if c in spec.capabilities)
            for name, spec in cfg.specialists.items()
        }
        best_name = min(cap_scores, key=lambda n: (-cap_scores[n], name_order[n]))
        if cap_scores[best_name] > 0:
            logger.debug(
                "Recruited specialist: %s (capability coverage=%d/%d, required=%s)",
                best_name, cap_scores[best_name], len(required_caps), required_caps,
            )
            return RecruitmentResult(
                specialist_id=best_name,
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
                specialist_id="engineering",
                required_capabilities=required_caps,
            )
        logger.debug("Recruited specialist: research (default fallback, no keywords matched)")
        return RecruitmentResult(
            specialist_id="research",
            required_capabilities=required_caps,
        )

    logger.debug(
        "Recruited specialist: %s (keyword score=%d)", best_name, best_score,
    )
    return RecruitmentResult(
        specialist_id=best_name,
        required_capabilities=required_caps,
    )
