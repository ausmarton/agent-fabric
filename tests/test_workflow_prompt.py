"""Tests for specialist system prompts: completeness and correctness."""
from __future__ import annotations

from agent_fabric.infrastructure.specialists.prompts import (
    SYSTEM_PROMPT_ENGINEERING,
    SYSTEM_PROMPT_RESEARCH,
)


def test_engineering_prompt_has_quality_rules():
    """Engineering prompt must mention key hard rules."""
    assert "quality" in SYSTEM_PROMPT_ENGINEERING.lower() or "Quality" in SYSTEM_PROMPT_ENGINEERING
    assert "finish_task" in SYSTEM_PROMPT_ENGINEERING
    assert "deploy" in SYSTEM_PROMPT_ENGINEERING.lower()


def test_research_prompt_has_citation_rules():
    """Research prompt must state that only fetched URLs may be cited."""
    assert "fetch_url" in SYSTEM_PROMPT_RESEARCH
    assert "fabricat" in SYSTEM_PROMPT_RESEARCH.lower() or "invent" in SYSTEM_PROMPT_RESEARCH.lower() or "Never" in SYSTEM_PROMPT_RESEARCH
    assert "finish_task" in SYSTEM_PROMPT_RESEARCH


def test_prompts_are_non_empty_strings():
    assert isinstance(SYSTEM_PROMPT_ENGINEERING, str) and len(SYSTEM_PROMPT_ENGINEERING) > 100
    assert isinstance(SYSTEM_PROMPT_RESEARCH, str) and len(SYSTEM_PROMPT_RESEARCH) > 100
