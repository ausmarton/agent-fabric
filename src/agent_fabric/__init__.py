__all__ = ['__version__']
__version__ = '0.1.0'

import logging

# Standard library convention for a library package: attach a NullHandler so
# that logging calls inside agent_fabric are silently discarded unless the
# *application* (CLI, HTTP server, test harness) configures handlers.
# This prevents "No handlers could be found for logger 'agent_fabric'" noise
# and ensures tests are silent by default.
logging.getLogger(__name__).addHandler(logging.NullHandler())
