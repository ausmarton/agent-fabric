"""Tests for Phase 2 capability inference and capability-based routing."""
from __future__ import annotations

import pytest
from agent_fabric.application.recruit import (
    RecruitmentResult,
    infer_capabilities,
    recruit_specialist,
)
from agent_fabric.config import DEFAULT_CONFIG
from agent_fabric.config.capabilities import CAPABILITY_KEYWORDS


# ---------------------------------------------------------------------------
# infer_capabilities
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("prompt,expected_caps", [
    # engineering prompts → code_execution
    ("build a Python service",                  ["code_execution"]),
    ("implement a pipeline in Scala",           ["code_execution"]),
    ("deploy to kubernetes",                    ["code_execution"]),
    # research prompts → systematic_review (possibly + citation_extraction)
    ("systematic review of literature",         ["systematic_review"]),
    ("survey papers on arxiv",                  ["systematic_review"]),
    # generic prompts → no capability inferred
    ("explore a topic",                         []),
    ("tell me about something",                 []),
])
def test_infer_capabilities_single_domain(prompt, expected_caps):
    caps = infer_capabilities(prompt, CAPABILITY_KEYWORDS)
    for cap in expected_caps:
        assert cap in caps


def test_infer_capabilities_empty_for_generic_prompt():
    """Prompts with no recognisable keywords produce an empty capability list."""
    assert infer_capabilities("explore a topic", CAPABILITY_KEYWORDS) == []
    assert infer_capabilities("tell me about something", CAPABILITY_KEYWORDS) == []


def test_infer_capabilities_multiple_domains():
    """A prompt spanning code + research yields capabilities from both domains."""
    caps = infer_capabilities(
        "build a tool that does a systematic review of arxiv papers",
        CAPABILITY_KEYWORDS,
    )
    assert "code_execution" in caps
    assert "systematic_review" in caps


def test_infer_capabilities_bibliography_and_citations():
    """'bibliography and citations' hits systematic_review and citation_extraction."""
    caps = infer_capabilities("bibliography and citations", CAPABILITY_KEYWORDS)
    assert "systematic_review" in caps
    assert "citation_extraction" in caps


def test_infer_capabilities_custom_keywords():
    """infer_capabilities works with any keyword map (not just CAPABILITY_KEYWORDS)."""
    kw_map = {
        "widget_painting": ["paint", "colour", "widget"],
        "rocket_science": ["launch", "orbit", "rocket"],
    }
    assert infer_capabilities("paint the widget red", kw_map) == ["widget_painting"]
    assert infer_capabilities("launch a rocket to orbit", kw_map) == ["rocket_science"]
    assert infer_capabilities("bake a cake", kw_map) == []


# ---------------------------------------------------------------------------
# RecruitmentResult carries capabilities
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("prompt,expected_cap", [
    ("build a Python service",        "code_execution"),
    ("systematic review of literature", "systematic_review"),
])
def test_recruitment_result_contains_capabilities(prompt, expected_cap):
    """recruit_specialist returns required_capabilities when routed by capability."""
    result = recruit_specialist(prompt, DEFAULT_CONFIG)
    assert isinstance(result, RecruitmentResult)
    assert expected_cap in result.required_capabilities


def test_recruitment_result_empty_caps_for_generic_prompt():
    """Prompts that fall back to keyword/hardcoded routing have empty required_capabilities."""
    result = recruit_specialist("explore a topic", DEFAULT_CONFIG)
    assert isinstance(result, RecruitmentResult)
    assert result.required_capabilities == []


# ---------------------------------------------------------------------------
# Routing selects the right pack via capabilities
# ---------------------------------------------------------------------------

def test_capability_routing_selects_engineering():
    result = recruit_specialist("build a Python service", DEFAULT_CONFIG)
    assert result.specialist_id == "engineering"
    assert "code_execution" in result.required_capabilities


def test_capability_routing_selects_research():
    result = recruit_specialist("systematic review of literature", DEFAULT_CONFIG)
    assert result.specialist_id == "research"
    assert "systematic_review" in result.required_capabilities


def test_mixed_prompt_routes_to_best_coverage():
    """A prompt needing both code and research capabilities selects the pack
    with the better coverage of required capabilities."""
    # "build a systematic review tool" → code_execution + systematic_review
    # engineering provides code_execution (1), research provides systematic_review (1)
    # Tie → config order → engineering (first in DEFAULT_CONFIG)
    result = recruit_specialist(
        "build a tool that does a systematic review of arxiv papers",
        DEFAULT_CONFIG,
    )
    # Both score 1 for the mixed prompt; engineering is first in config so wins.
    assert result.specialist_id == "engineering"
    assert "code_execution" in result.required_capabilities
    assert "systematic_review" in result.required_capabilities
