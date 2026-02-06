"""CID el Dill client."""

__version__ = "0.1.0"
__all__ = [
    "configure_debug",
    "with_debug",
    "debug_call",
    "async_debug_call",
]

from .with_debug import async_debug_call, configure_debug, debug_call, with_debug
