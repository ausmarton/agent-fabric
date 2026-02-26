"""Specialist registry: resolve pack by id from config.

Pack selection order for a given specialist_id:
1. If ``SpecialistConfig.builder`` is set, dynamically import and call that factory.
2. Otherwise look up the built-in ``_DEFAULT_BUILDERS`` map.
3. If neither exists, raise ``ValueError``.

Adding a new pack without editing this file:
- Set ``builder: "mypackage.packs.custom:build_custom_pack"`` in your YAML config.
- The factory must have signature ``(workspace_path: str, network_allowed: bool) -> SpecialistPack``.
"""

from __future__ import annotations

import importlib
import logging
from typing import Callable, List

from agentic_concierge.config import ConciergeConfig
from agentic_concierge.application.ports import SpecialistPack, SpecialistRegistry
from agentic_concierge.config.features import FeatureSet, ProfileTier

from .engineering import build_engineering_pack
from .enterprise_research import build_enterprise_research_pack
from .research import build_research_pack

logger = logging.getLogger(__name__)

# Built-in packs. To add a new built-in: register it here.
# External / custom packs: set SpecialistConfig.builder in config instead.
_DEFAULT_BUILDERS: dict[str, Callable[[str, bool], SpecialistPack]] = {
    "engineering": build_engineering_pack,
    "enterprise_research": build_enterprise_research_pack,
    "research": build_research_pack,
}


def _load_builder(dotted_path: str) -> Callable[[str, bool], SpecialistPack]:
    """Import and return a pack factory from a dotted path (``'module.path:func_name'``)."""
    if ":" not in dotted_path:
        raise ValueError(
            f"Invalid builder path {dotted_path!r}: expected 'module.path:function_name'"
        )
    module_path, func_name = dotted_path.rsplit(":", 1)
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise ImportError(
            f"Cannot import builder module {module_path!r}: {exc}"
        ) from exc
    try:
        func = getattr(module, func_name)
    except AttributeError as exc:
        raise ImportError(
            f"Module {module_path!r} has no attribute {func_name!r}"
        ) from exc
    return func


class ConfigSpecialistRegistry(SpecialistRegistry):
    """Resolve specialist pack by id; only specialists declared in config are available.

    If ``SpecialistConfig.builder`` is set for a specialist, the factory at that
    dotted import path is loaded and called. Otherwise the built-in ``_DEFAULT_BUILDERS``
    map is consulted. Raises ``ValueError`` if neither source provides an implementation.
    """

    def __init__(self, config: ConciergeConfig):
        self._config = config
        self._feature_set = self._load_feature_set()

    def _load_feature_set(self) -> FeatureSet:
        """Detect the profile tier once and build the feature set.

        Called once in ``__init__`` so ``load_detected()`` is not invoked on
        every ``get_pack()`` call.  Falls back to ``ProfileTier.SMALL`` when
        no bootstrap data exists (first-time users).
        """
        try:
            from agentic_concierge.bootstrap.detected import load_detected
            detected = load_detected()
            tier = detected.tier if detected is not None else ProfileTier.SMALL
        except Exception:
            tier = ProfileTier.SMALL
        return FeatureSet.from_profile(tier, self._config.features)

    def get_pack(
        self,
        specialist_id: str,
        workspace_path: str,
        network_allowed: bool,
    ) -> SpecialistPack:
        if specialist_id not in self._config.specialists:
            raise ValueError(f"Unknown specialist: {specialist_id!r}")

        spec_cfg = self._config.specialists[specialist_id]

        if spec_cfg.builder:
            logger.debug(
                "Loading custom builder for %r: %s", specialist_id, spec_cfg.builder
            )
            builder = _load_builder(spec_cfg.builder)
        elif specialist_id in _DEFAULT_BUILDERS:
            builder = _DEFAULT_BUILDERS[specialist_id]
        else:
            raise ValueError(
                f"No pack implementation for specialist {specialist_id!r}. "
                "Set 'builder' in config to point at a pack factory function."
            )

        pack = builder(workspace_path, network_allowed)

        # Attach the feature set via the public API so aopen() can conditionally
        # register browser tools and other feature-gated extensions.
        if hasattr(pack, "set_feature_set"):
            pack.set_feature_set(self._feature_set)

        if spec_cfg.mcp_servers:
            try:
                from agentic_concierge.infrastructure.mcp import MCPAugmentedPack, MCPSessionManager
            except ImportError as exc:
                raise RuntimeError(
                    "mcp_servers configured but 'mcp' package is not installed. "
                    "Install with: pip install agentic-concierge[mcp]"
                ) from exc
            sessions = [MCPSessionManager(s) for s in spec_cfg.mcp_servers]
            pack = MCPAugmentedPack(pack, sessions)
            logger.debug(
                "Wrapped pack %r with MCPAugmentedPack (%d server(s))",
                specialist_id, len(sessions),
            )

        if spec_cfg.container_image:
            from agentic_concierge.infrastructure.specialists.containerised import (
                ContainerisedSpecialistPack,
            )
            pack = ContainerisedSpecialistPack(pack, spec_cfg.container_image, workspace_path)
            logger.debug(
                "Wrapped pack %r with ContainerisedSpecialistPack (image=%r)",
                specialist_id, spec_cfg.container_image,
            )

        return pack

    def list_ids(self) -> List[str]:
        return list(self._config.specialists.keys())
