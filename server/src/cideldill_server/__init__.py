"""CID el Dill server package."""

__version__ = "0.1.0"
__all__ = [
    "BreakpointManager",
    "BreakpointServer",
    "CASStore",
    "CIDStore",
]

from .breakpoint_manager import BreakpointManager
from .cas_store import CASStore
from .cid_store import CIDStore

try:
    from .breakpoint_server import BreakpointServer
except Exception:  # pragma: no cover - optional dependency (flask)
    BreakpointServer = None  # type: ignore[assignment]
