"""Tests for bootstrap/model_advisor.py — ProfileTier selection and SystemProfile."""

from __future__ import annotations

import pytest

from agentic_concierge.bootstrap.model_advisor import SystemProfile, advise_profile
from agentic_concierge.bootstrap.system_probe import GPUDevice, SystemProbe
from agentic_concierge.config.features import ProfileTier


def _probe(
    ram_mb: int,
    available_mb: int = None,
    cpu_cores: int = 8,
    gpu_devices=None,
) -> SystemProbe:
    return SystemProbe(
        cpu_cores=cpu_cores,
        cpu_arch="x86_64",
        ram_total_mb=ram_mb,
        ram_available_mb=available_mb if available_mb is not None else ram_mb // 2,
        gpu_devices=gpu_devices or [],
    )


# ---------------------------------------------------------------------------
# Tier selection
# ---------------------------------------------------------------------------

def test_nano_tier():
    profile = advise_profile(_probe(4 * 1024))  # 4 GB RAM
    assert profile.tier == ProfileTier.NANO


def test_small_tier():
    profile = advise_profile(_probe(8 * 1024))  # exactly 8 GB
    assert profile.tier == ProfileTier.SMALL


def test_small_tier_12gb():
    profile = advise_profile(_probe(12 * 1024))
    assert profile.tier == ProfileTier.SMALL


def test_medium_tier_ram():
    profile = advise_profile(_probe(16 * 1024))  # exactly 16 GB
    assert profile.tier == ProfileTier.MEDIUM


def test_medium_tier_vram():
    gpu = GPUDevice(name="GPU", vram_mb=6 * 1024, vendor="nvidia")
    # 12 GB RAM but 6 GB VRAM → medium
    profile = advise_profile(_probe(12 * 1024, gpu_devices=[gpu]))
    assert profile.tier == ProfileTier.MEDIUM


def test_large_tier():
    profile = advise_profile(_probe(32 * 1024))  # 32 GB RAM
    assert profile.tier == ProfileTier.LARGE


def test_server_tier_ram():
    profile = advise_profile(_probe(64 * 1024))  # 64 GB RAM
    assert profile.tier == ProfileTier.SERVER


def test_server_tier_multi_gpu():
    gpus = [
        GPUDevice(name="GPU A", vram_mb=8192, vendor="nvidia"),
        GPUDevice(name="GPU B", vram_mb=8192, vendor="nvidia"),
    ]
    # Only 12 GB RAM but 2+ GPUs → server
    profile = advise_profile(_probe(12 * 1024, gpu_devices=gpus))
    assert profile.tier == ProfileTier.SERVER


def test_server_tier_high_vram():
    gpu = GPUDevice(name="A100", vram_mb=40960, vendor="nvidia")
    profile = advise_profile(_probe(32 * 1024, gpu_devices=[gpu]))
    assert profile.tier == ProfileTier.SERVER


# ---------------------------------------------------------------------------
# Model recommendations
# ---------------------------------------------------------------------------

def test_nano_models():
    profile = advise_profile(_probe(4 * 1024))
    assert profile.fast_model == "qwen2.5:3b"
    assert profile.routing_model == "qwen2.5:0.5b"


def test_server_models():
    profile = advise_profile(_probe(128 * 1024))
    assert profile.quality_model == "qwen2.5:72b"
    assert profile.fast_model == "qwen2.5:32b"


# ---------------------------------------------------------------------------
# max_concurrent_agents
# ---------------------------------------------------------------------------

def test_max_concurrent_always_at_least_one():
    # Very little RAM available
    probe = _probe(4 * 1024, available_mb=512, cpu_cores=2)
    profile = advise_profile(probe)
    assert profile.max_concurrent_agents >= 1


def test_max_concurrent_bounded_by_cpu_minus_one():
    probe = _probe(64 * 1024, available_mb=32 * 1024, cpu_cores=3)
    profile = advise_profile(probe)
    # cpu_cores - 1 = 2
    assert profile.max_concurrent_agents <= 2
