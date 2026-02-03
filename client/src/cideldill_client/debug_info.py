"""Debug info object for with_debug configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class DebugInfo:
    """Information about current debug configuration."""

    enabled: bool
    server: Optional[str]
    status: str

    def is_enabled(self) -> bool:
        """Return whether debugging is enabled."""
        return self.enabled

    def server_url(self) -> Optional[str]:
        """Return the debug server URL if enabled."""
        return self.server

    def connection_status(self) -> str:
        """Return connection status."""
        return self.status
