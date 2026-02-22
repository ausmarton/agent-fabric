"""Configuration: schema and loading from env/file."""

from .schema import DEFAULT_CONFIG, FabricConfig, ModelConfig, SpecialistConfig
from .loader import load_config

get_config = load_config  # alias

__all__ = ["DEFAULT_CONFIG", "FabricConfig", "ModelConfig", "SpecialistConfig", "load_config", "get_config"]
