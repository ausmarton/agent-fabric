"""Tests for JSON extraction from model output."""
from __future__ import annotations

import pytest
from agent_fabric.application.json_parsing import extract_json


def test_full_json():
    ok, obj, err = extract_json('{"action": "final", "x": 1}')
    assert ok is True
    assert obj == {"action": "final", "x": 1}
    assert err == ""


def test_json_with_surrounding_text():
    text = 'Here is the result:\n{"action": "tool", "tool_name": "shell", "args": {"cmd": ["ls"]}}\nDone.'
    ok, obj, err = extract_json(text)
    assert ok is True
    assert obj["action"] == "tool"
    assert obj["tool_name"] == "shell"


def test_invalid_no_brace():
    ok, obj, err = extract_json("no json here")
    assert ok is False
    assert obj is None
    assert "No JSON object found" in err or "Failed" in err


def test_invalid_malformed_json():
    ok, obj, err = extract_json('{"action": "final", broken}')
    assert ok is False
    assert obj is None
