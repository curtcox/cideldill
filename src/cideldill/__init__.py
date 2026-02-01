"""CID el Dill.

A Python library for logging execution to a remote inspector/debugger/configuration agent.
"""

__version__ = "0.1.0"
__all__ = ["Logger", "Inspector"]

from .inspector import Inspector
from .logger import Logger
