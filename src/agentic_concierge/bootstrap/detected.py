"""Cross-platform detected.json: persist and load the detected SystemProfile.

Uses ``platformdirs`` to store the file in the OS-appropriate user data
directory:

- Linux:   ``~/.local/share/agentic-concierge/detected.json``
- macOS:   ``~/Library/Application Support/agentic-concierge/detected.json``
- Windows: ``%LOCALAPPDATA%\\agentic-concierge\\detected.json``
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from agentic_concierge.config.features import ProfileTier

if TYPE_CHECKING:
    from agentic_concierge.bootstrap.model_advisor import SystemProfile

logger = logging.getLogger(__name__)


def detected_path() -> Path:
    """Return the OS-appropriate path for ``detected.json``."""
    try:
        from platformdirs import user_data_path
        base = Path(user_data_path("agentic-concierge"))
    except Exception:
        import os
        base = Path(os.path.expanduser("~")) / ".agentic-concierge"
    base.mkdir(parents=True, exist_ok=True)
    return base / "detected.json"


def save_detected(profile: "SystemProfile", path: Optional[Path] = None) -> None:  # type: ignore[name-defined]
    """Persist *profile* to ``detected.json``.

    *path* overrides the default ``detected_path()`` — useful in tests.
    """
    from agentic_concierge.bootstrap.model_advisor import SystemProfile  # noqa: F401
    dest = path or detected_path()
    data = {
        "tier": profile.tier.value,
        "routing_model": profile.routing_model,
        "fast_model": profile.fast_model,
        "quality_model": profile.quality_model,
        "max_concurrent_agents": profile.max_concurrent_agents,
        "ram_total_mb": profile.ram_total_mb,
        "ram_available_mb": profile.ram_available_mb,
        "total_vram_mb": profile.total_vram_mb,
        "cpu_cores": profile.cpu_cores,
        "cpu_arch": profile.cpu_arch,
        "gpu_count": profile.gpu_count,
    }
    dest.write_text(json.dumps(data, indent=2), encoding="utf-8")
    logger.debug("Saved detected profile %s to %s", profile.tier.value, dest)


def load_detected(path: Optional[Path] = None) -> "Optional[SystemProfile]":  # type: ignore[name-defined]
    """Load ``detected.json`` and return a ``SystemProfile``, or ``None`` if missing/corrupt."""
    from agentic_concierge.bootstrap.model_advisor import SystemProfile
    src = path or detected_path()
    if not src.exists():
        return None
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
        return SystemProfile(
            tier=ProfileTier(data["tier"]),
            routing_model=data["routing_model"],
            fast_model=data["fast_model"],
            quality_model=data["quality_model"],
            max_concurrent_agents=data["max_concurrent_agents"],
            ram_total_mb=data["ram_total_mb"],
            ram_available_mb=data["ram_available_mb"],
            total_vram_mb=data["total_vram_mb"],
            cpu_cores=data["cpu_cores"],
            cpu_arch=data["cpu_arch"],
            gpu_count=data["gpu_count"],
        )
    except (KeyError, ValueError, json.JSONDecodeError) as e:
        logger.warning("detected.json corrupt or incompatible (%s); ignoring.", e)
        return None


def is_first_run(path: Optional[Path] = None) -> bool:
    """Return ``True`` if ``detected.json`` does not yet exist (first run)."""
    return not (path or detected_path()).exists()
