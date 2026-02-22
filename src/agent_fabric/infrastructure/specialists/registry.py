"""Specialist registry: resolve pack by id from config."""

from __future__ import annotations

from typing import Callable, List

from agent_fabric.config import FabricConfig
from agent_fabric.application.ports import SpecialistPack, SpecialistRegistry

from .engineering import build_engineering_pack
from .research import build_research_pack

_BUILDERS: dict[str, Callable[[str, bool], SpecialistPack]] = {
    "engineering": build_engineering_pack,
    "research": build_research_pack,
}


class ConfigSpecialistRegistry(SpecialistRegistry):
    """Resolve specialist pack by id; only specialists in config are available."""

    def __init__(self, config: FabricConfig):
        self._config = config

    def get_pack(
        self,
        specialist_id: str,
        workspace_path: str,
        network_allowed: bool,
    ) -> SpecialistPack:
        if specialist_id not in self._config.specialists:
            raise ValueError(f"Unknown specialist: {specialist_id}")
        if specialist_id not in _BUILDERS:
            raise ValueError(f"No pack implementation for specialist: {specialist_id}")
        return _BUILDERS[specialist_id](workspace_path, network_allowed)

    def list_ids(self) -> List[str]:
        return list(self._config.specialists.keys())
