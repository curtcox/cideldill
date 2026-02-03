"""Port discovery utilities for client."""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def get_discovery_file_path() -> Path:
    """Get the path to the port discovery file.

    Returns:
        Path to ~/.cideldill/port
    """
    return Path.home() / ".cideldill" / "port"


def read_port_from_discovery_file() -> Optional[int]:
    """Read the server port from the discovery file.

    Returns:
        The port number, or None if file doesn't exist or is invalid.
    """
    port_file = get_discovery_file_path()

    if not port_file.exists():
        return None

    try:
        port = int(port_file.read_text().strip())
    except (ValueError, OSError):
        return None

    if not (1 <= port <= 65535):
        return None

    return port
