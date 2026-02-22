"""Tests for config loading."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from agent_fabric.config import DEFAULT_CONFIG, FabricConfig, get_config
from agent_fabric.config import loader as config_loader


def test_get_config_default(monkeypatch):
    monkeypatch.delenv("FABRIC_CONFIG_PATH", raising=False)
    monkeypatch.setattr(config_loader, "_env", None)
    cfg = get_config()
    assert cfg is DEFAULT_CONFIG
    assert "engineering" in cfg.specialists
    assert "quality" in cfg.models


def test_get_config_from_file(monkeypatch):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({
            "models": {
                "custom": {
                    "base_url": "http://127.0.0.1:9000/v1",
                    "model": "my-model",
                    "temperature": 0.2,
                    "max_tokens": 1000,
                }
            },
            "specialists": DEFAULT_CONFIG.model_dump()["specialists"],
        }, f)
        path = f.name
    try:
        monkeypatch.setenv("FABRIC_CONFIG_PATH", path)
        monkeypatch.setattr(config_loader, "_env", None)
        cfg = get_config()
        assert cfg.models["custom"].model == "my-model"
        assert cfg.models["custom"].temperature == 0.2
    finally:
        Path(path).unlink(missing_ok=True)


def test_config_local_llm_default():
    """Local LLM is default and primary: ensure_available is True by default."""
    assert DEFAULT_CONFIG.local_llm_ensure_available is True
    assert DEFAULT_CONFIG.local_llm_start_cmd == ["ollama", "serve"]
    assert DEFAULT_CONFIG.local_llm_start_timeout_s == 90


def test_config_local_llm_from_file(monkeypatch):
    """New key names load correctly."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({
            "models": DEFAULT_CONFIG.model_dump()["models"],
            "specialists": DEFAULT_CONFIG.model_dump()["specialists"],
            "local_llm_ensure_available": False,
            "local_llm_start_cmd": ["/usr/bin/ollama", "serve"],
            "local_llm_start_timeout_s": 120,
        }, f)
        path = f.name
    try:
        monkeypatch.setenv("FABRIC_CONFIG_PATH", path)
        monkeypatch.setattr(config_loader, "_env", None)
        cfg = get_config()
        assert cfg.local_llm_ensure_available is False
        assert cfg.local_llm_start_cmd == ["/usr/bin/ollama", "serve"]
        assert cfg.local_llm_start_timeout_s == 120
    finally:
        Path(path).unlink(missing_ok=True)


def test_config_legacy_auto_start_llm_keys(monkeypatch):
    """Legacy auto_start_llm / llm_start_cmd / llm_start_timeout_s map to new names."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({
            "models": DEFAULT_CONFIG.model_dump()["models"],
            "specialists": DEFAULT_CONFIG.model_dump()["specialists"],
            "auto_start_llm": True,
            "llm_start_cmd": ["/usr/bin/ollama", "serve"],
            "llm_start_timeout_s": 120,
        }, f)
        path = f.name
    try:
        monkeypatch.setenv("FABRIC_CONFIG_PATH", path)
        monkeypatch.setattr(config_loader, "_env", None)
        cfg = get_config()
        assert cfg.local_llm_ensure_available is True
        assert cfg.local_llm_start_cmd == ["/usr/bin/ollama", "serve"]
        assert cfg.local_llm_start_timeout_s == 120
    finally:
        Path(path).unlink(missing_ok=True)
