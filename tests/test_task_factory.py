"""Tests for build_task() — Task construction with pack normalisation."""
from __future__ import annotations

import pytest
from agentic_concierge.domain import build_task


@pytest.mark.parametrize("pack,expected_specialist_id", [
    (None,          None),           # absent pack → auto-routing
    ("",            None),           # empty string → auto-routing
    ("   ",         None),           # whitespace-only → auto-routing
    ("engineering", "engineering"),  # exact match preserved
    (" research ",  "research"),     # surrounding whitespace stripped
])
def test_build_task_pack_normalisation(pack, expected_specialist_id):
    task = build_task(
        prompt="do something",
        pack=pack,
        model_key="quality",
        network_allowed=True,
    )
    assert task.specialist_id == expected_specialist_id


def test_build_task_passes_remaining_fields():
    task = build_task("my prompt", "engineering", "fast", False)
    assert task.prompt == "my prompt"
    assert task.model_key == "fast"
    assert task.network_allowed is False
