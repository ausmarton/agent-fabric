"""Tests for Phase 2 capability inference and capability-based routing."""
from __future__ import annotations

import pytest
from agentic_concierge.application.recruit import (
    RecruitmentResult,
    infer_capabilities,
    recruit_specialist,
)
from agentic_concierge.config import DEFAULT_CONFIG
from agentic_concierge.config.capabilities import CAPABILITY_KEYWORDS


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


def test_mixed_prompt_routes_to_task_force():
    """A prompt needing capabilities that span both packs recruits a task force.

    "build a systematic review tool" needs code_execution (engineering) AND
    systematic_review (research).  Neither pack alone can cover both, so the
    greedy selector picks both — returning a task force.
    """
    result = recruit_specialist(
        "build a tool that does a systematic review of arxiv papers",
        DEFAULT_CONFIG,
    )
    assert result.is_task_force, "Mixed-capability prompt must recruit a task force"
    assert "engineering" in result.specialist_ids
    assert "research" in result.specialist_ids
    assert "code_execution" in result.required_capabilities
    assert "systematic_review" in result.required_capabilities


def test_single_capability_prompt_is_not_task_force():
    """A prompt that maps to a single pack does not form a task force."""
    result = recruit_specialist("build a Python service", DEFAULT_CONFIG)
    assert not result.is_task_force
    assert result.specialist_ids == ["engineering"]


def test_task_force_specialist_ids_in_config_order():
    """Task force specialist_ids are always in config insertion order."""
    result = recruit_specialist(
        "build a tool that does a systematic review of arxiv papers",
        DEFAULT_CONFIG,
    )
    # engineering is declared before research in DEFAULT_CONFIG.
    specialists_list = list(DEFAULT_CONFIG.specialists.keys())
    eng_idx = specialists_list.index("engineering")
    res_idx = specialists_list.index("research")
    assert eng_idx < res_idx
    # specialist_ids must follow the same order.
    assert result.specialist_ids.index("engineering") < result.specialist_ids.index("research")
