"""Tests for keyword-based recruitment (recruit_specialist)."""
from __future__ import annotations

import pytest
from agent_fabric.application.recruit import recruit_specialist
from agent_fabric.config import DEFAULT_CONFIG
from agent_fabric.config.schema import FabricConfig, SpecialistConfig


@pytest.mark.parametrize("prompt,expected", [
    # engineering keywords
    ("I need to build a Python service", "engineering"),
    ("implement a pipeline in Scala", "engineering"),
    ("deploy to kubernetes", "engineering"),
    # research keywords
    ("systematic review of literature", "research"),
    ("survey papers on arxiv", "research"),
    ("bibliography and citations", "research"),
])
def test_keyword_routing(prompt, expected):
    assert recruit_specialist(prompt, DEFAULT_CONFIG) == expected


@pytest.mark.parametrize("prompt,expected", [
    ("write some code", "engineering"),
    ("build a small API", "engineering"),
    ("explore a topic", "research"),
    ("tell me about something", "research"),
])
def test_fallback_routing(prompt, expected):
    assert recruit_specialist(prompt, DEFAULT_CONFIG) == expected


def _make_tie_config(first: str, second: str) -> FabricConfig:
    """Two specialists sharing the same keyword; order controls tie-break."""
    return FabricConfig(
        models=DEFAULT_CONFIG.models,
        specialists={
            first: SpecialistConfig(description=first, keywords=["foo"], workflow=first),
            second: SpecialistConfig(description=second, keywords=["foo"], workflow=second),
        },
    )


@pytest.mark.parametrize("first,second,expected", [
    ("alpha", "beta", "alpha"),  # alpha listed first → wins the tie
    ("beta", "alpha", "beta"),   # beta listed first → wins the tie
])
def test_tie_break_uses_config_order(first, second, expected):
    """When two specialists score equally, the one first in config wins."""
    config = _make_tie_config(first, second)
    assert recruit_specialist("foo bar", config) == expected
