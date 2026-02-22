"""Recruit specialist(s) for a task. Today: keyword-based, single specialist."""

from __future__ import annotations

from agent_fabric.config import FabricConfig


def recruit_specialist(prompt: str, cfg: FabricConfig) -> str:
    """
    Choose one specialist id from config based on prompt.
    Returns specialist id (e.g. 'engineering' or 'research').
    """
    p = prompt.lower()
    scores: dict[str, int] = {name: 0 for name in cfg.specialists}
    for name, spec in cfg.specialists.items():
        for kw in spec.keywords:
            if kw in p:
                scores[name] += 1
    best_name, best_score = max(scores.items(), key=lambda kv: kv[1])
    if best_score == 0:
        if any(x in p for x in ["code", "build", "implement", "service", "pipeline", "deploy"]):
            return "engineering"
        return "research"
    return best_name
