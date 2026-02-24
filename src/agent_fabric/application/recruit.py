"""Recruit specialist(s) for a task. Today: keyword-based, single specialist."""

from __future__ import annotations

import logging

from agent_fabric.config import FabricConfig

logger = logging.getLogger(__name__)


def recruit_specialist(prompt: str, cfg: FabricConfig) -> str:
    """
    Choose one specialist id from config based on prompt.
    Returns specialist id (e.g. 'engineering' or 'research').

    Scoring: each keyword found in the lowercased prompt adds 1 to that
    specialist's score.  The highest-scoring specialist wins.

    Tie-breaking: when two or more specialists share the top score, the one
    that appears *first* in ``cfg.specialists`` (config insertion order) wins.
    This is deterministic in Python 3.7+ and gives operators control over
    priority via config ordering.
    """
    p = prompt.lower()
    scores: dict[str, int] = {name: 0 for name in cfg.specialists}
    for name, spec in cfg.specialists.items():
        for kw in spec.keywords:
            if kw in p:
                scores[name] += 1

    # Explicit tie-break: sort by (-score, config_index) so the highest score
    # wins and ties resolve to whichever specialist is listed first in config.
    name_order = {name: i for i, name in enumerate(cfg.specialists)}
    best_name = min(scores, key=lambda name: (-scores[name], name_order[name]))
    best_score = scores[best_name]

    if best_score == 0:
        if any(x in p for x in ["code", "build", "implement", "service", "pipeline", "deploy"]):
            logger.debug("Recruited specialist: engineering (hardcoded keyword fallback)")
            return "engineering"
        logger.debug("Recruited specialist: research (default fallback, no keywords matched)")
        return "research"
    logger.debug("Recruited specialist: %s (keyword score=%d)", best_name, best_score)
    return best_name
