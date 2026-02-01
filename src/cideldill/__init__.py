"""CID el Dill - A Python library for logging execution to a remote inspector/debugger/configuration agent."""

__version__ = "0.1.0"
__all__ = ["Logger", "Inspector"]

from .logger import Logger
from .inspector import Inspector
