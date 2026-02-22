"""Tests for keyword-based recruitment (recruit_specialist)."""
from __future__ import annotations

import pytest
from agent_fabric.application.recruit import recruit_specialist
from agent_fabric.config import DEFAULT_CONFIG


def test_recruit_engineering_keywords():
    assert recruit_specialist("I need to build a Python service", DEFAULT_CONFIG) == "engineering"
    assert recruit_specialist("implement a pipeline in Scala", DEFAULT_CONFIG) == "engineering"
    assert recruit_specialist("deploy to kubernetes", DEFAULT_CONFIG) == "engineering"


def test_recruit_research_keywords():
    assert recruit_specialist("systematic review of literature", DEFAULT_CONFIG) == "research"
    assert recruit_specialist("survey papers on arxiv", DEFAULT_CONFIG) == "research"
    assert recruit_specialist("bibliography and citations", DEFAULT_CONFIG) == "research"


def test_recruit_fallback_engineering():
    assert recruit_specialist("write some code", DEFAULT_CONFIG) == "engineering"
    assert recruit_specialist("build a small API", DEFAULT_CONFIG) == "engineering"


def test_recruit_fallback_research():
    assert recruit_specialist("explore a topic", DEFAULT_CONFIG) == "research"
    assert recruit_specialist("tell me about something", DEFAULT_CONFIG) == "research"
