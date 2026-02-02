"""CID el Dill.

A Python library for logging execution to a remote inspector/debugger/configuration agent.
"""

__version__ = "0.1.0"
__all__ = [
    "configure_debug",
    "with_debug",
]

from .with_debug import configure_debug, with_debug
