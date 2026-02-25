from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("agent-fabric")
except PackageNotFoundError:
    # Package not installed (e.g. running from source without pip install)
    __version__ = "0.0.0.dev0"

__all__ = ["__version__"]

import logging

# Standard library convention for a library package: attach a NullHandler so
# that logging calls inside agent_fabric are silently discarded unless the
# *application* (CLI, HTTP server, test harness) configures handlers.
logging.getLogger(__name__).addHandler(logging.NullHandler())
