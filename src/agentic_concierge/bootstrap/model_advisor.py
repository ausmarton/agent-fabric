"""Model advisor: recommend profile tier and models based on system resources.

Given a ``SystemProbe`` snapshot, ``advise_profile()`` determines the
``ProfileTier`` and returns a ``SystemProfile`` with the recommended models
for that tier.  All recommendations use models known to support native tool
calling.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentic_concierge.config.features import ProfileTier

if TYPE_CHECKING:
    from agentic_concierge.bootstrap.system_probe import SystemProbe


# Model recommendations per tier (all support native tool calling).
# Routing model is always qwen2.5:0.5b — small, fast, and cheap for routing.
_MODEL_TABLE: dict[ProfileTier, dict[str, str]] = {
    ProfileTier.NANO:   {"routing": "qwen2.5:0.5b", "fast": "qwen2.5:3b",  "quality": "phi3:mini"},
    ProfileTier.SMALL:  {"routing": "qwen2.5:0.5b", "fast": "qwen2.5:7b",  "quality": "qwen2.5:7b"},
    ProfileTier.MEDIUM: {"routing": "qwen2.5:0.5b", "fast": "qwen2.5:7b",  "quality": "qwen2.5:14b"},
    ProfileTier.LARGE:  {"routing": "qwen2.5:0.5b", "fast": "qwen2.5:14b", "quality": "qwen2.5:32b"},
    ProfileTier.SERVER: {"routing": "qwen2.5:0.5b", "fast": "qwen2.5:32b", "quality": "qwen2.5:72b"},
}

# Approximate RAM each model needs for its KV-cache context window (~2 GB default).
_MODEL_CTX_MB = 2048


@dataclass
class SystemProfile:
    """Recommended configuration derived from the detected hardware."""

    tier: ProfileTier
    routing_model: str
    fast_model: str
    quality_model: str
    max_concurrent_agents: int
    ram_total_mb: int
    ram_available_mb: int
    total_vram_mb: int
    cpu_cores: int
    cpu_arch: str
    gpu_count: int


def advise_profile(probe: "SystemProbe") -> SystemProfile:
    """Derive the best ``SystemProfile`` for the detected hardware.

    Tier thresholds:

    ========  ============================================
    nano      RAM < 8 GB (regardless of GPU)
    small     8–16 GB RAM, total VRAM < 4 GB
    medium    16–32 GB RAM OR 4–12 GB VRAM
    large     32–64 GB RAM OR 12–24 GB VRAM
    server    64+ GB RAM OR 24+ GB VRAM OR 2+ GPUs
    ========  ============================================
    """
    total_vram_mb = probe.total_vram_mb
    vram_gb = total_vram_mb / 1024
    gpu_count = len(probe.gpu_devices)

    if gpu_count >= 2 or probe.ram_total_mb >= 64 * 1024 or vram_gb >= 24:
        tier = ProfileTier.SERVER
    elif probe.ram_total_mb >= 32 * 1024 or vram_gb >= 12:
        tier = ProfileTier.LARGE
    elif probe.ram_total_mb >= 16 * 1024 or vram_gb >= 4:
        tier = ProfileTier.MEDIUM
    elif probe.ram_total_mb >= 8 * 1024:
        tier = ProfileTier.SMALL
    else:
        tier = ProfileTier.NANO

    models = _MODEL_TABLE[tier]

    # max_concurrent_agents: leave 15% + 512 MB overhead; each agent needs ~2 GB
    overhead_mb = max(2048, probe.ram_total_mb * 0.15) + 512
    usable_mb = probe.ram_available_mb - overhead_mb
    max_concurrent = max(1, min(math.floor(usable_mb / _MODEL_CTX_MB), probe.cpu_cores - 1))

    return SystemProfile(
        tier=tier,
        routing_model=models["routing"],
        fast_model=models["fast"],
        quality_model=models["quality"],
        max_concurrent_agents=max_concurrent,
        ram_total_mb=probe.ram_total_mb,
        ram_available_mb=probe.ram_available_mb,
        total_vram_mb=total_vram_mb,
        cpu_cores=probe.cpu_cores,
        cpu_arch=probe.cpu_arch,
        gpu_count=gpu_count,
    )
